"""Browser session: headed by default, headless only when a benchmark asks for it.

Two ways to get a tab:

* launch a Playwright-managed Chromium (the default — a real window you can watch);
* attach to an already-running Chrome over CDP (`--cdp http://127.0.0.1:9222`), which is
  how the pre-existing `chrome-visible` process is driven. Attaching never closes it.

Either way the page gets two init scripts, both installed before any navigation:

* a seeded `Math.random`, and a clear of the game the page would otherwise resume — the game
  spawns tiles in exactly two calls to `Math.random` per new tile (the value, then the cell),
  so replacing it makes the whole spawn sequence a function of the seed;
* a render shim: the game's own background painted before its stylesheet arrives (so a
  between-games reload does not flash white), and a `requestAnimationFrame` with a timer
  fallback (the game boots and renders inside a frame, and would otherwise freeze in a window
  the compositor has stopped painting).
"""

import asyncio

import labpaths  # noqa: F401

# `python3 -m http.server` speaks HTTP/1.0: one connection per file, closed as soon as the
# response is written, with a listen backlog of 5. A page needs about a dozen files, so two
# browsers loading at the same instant already overshoot that backlog, and the page arrives
# without its scripts (`net::ERR_CONNECTION_RESET`, no tiles, no error of its own). Page
# loads are therefore serialized process-wide. A load takes well under a second, so this
# costs a fraction of a second per game and removes the failure entirely.
# `style/main.css` paints the page this colour; using it as the browser's default background
# removes the white flash of a navigation.
GAME_BACKGROUND = {"r": 250, "g": 248, "b": 239, "a": 1}

NAVIGATION_GATE = asyncio.Semaphore(1)

RNG_JS = r"""
(() => {
  const raw = new URLSearchParams(location.search).get("seed");
  if (raw === null) return;
  // Drop the game the page would otherwise resume. The page saves its grid inside a
  // requestAnimationFrame, so clearing storage from the driver after load races that save:
  // if the save lands last, the next navigation resumes an old board instead of dealing the
  // two start tiles, and the seeded spawn stream shifts by however many tiles it resumed.
  // Clearing at document start, before the game's own scripts parse, removes the race.
  try { localStorage.removeItem("gameState"); } catch (error) { /* storage may be denied */ }
  let state = (Number(raw) >>> 0) || 1;
  Math.random = () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
})()
"""

RENDER_JS = r"""
(() => {
  // The game constructs its GameManager inside a requestAnimationFrame and renders every
  // move inside one, so a compositor that stops delivering frames for an occluded window
  // stops the game entirely — it never even deals its first tiles. This wraps rAF with a
  // timer fallback: the real frame is used whenever it arrives, and a late one is delivered
  // by the timer instead. It only fires when a frame is more than 250 ms late, so a visible
  // window behaves exactly as before.
  const nativeFrame = window.requestAnimationFrame.bind(window);
  const nativeCancel = window.cancelAnimationFrame.bind(window);
  const timers = new Map();
  window.requestAnimationFrame = (callback) => {
    let fired = false;
    const id = nativeFrame((time) => {
      if (fired) return;
      fired = true;
      const timer = timers.get(id);
      if (timer !== undefined) { clearTimeout(timer); timers.delete(id); }
      callback(time);
    });
    timers.set(id, setTimeout(() => {
      if (fired) return;
      fired = true;
      timers.delete(id);
      try { nativeCancel(id); } catch (error) { /* frame already delivered */ }
      callback(performance.now());
    }, 250));
    return id;
  };
  window.cancelAnimationFrame = (id) => {
    const timer = timers.get(id);
    if (timer !== undefined) { clearTimeout(timer); timers.delete(id); }
    nativeCancel(id);
  };
})()
"""


class Tab:
    """The three-method surface `game_client.GameClient` drives."""

    def __init__(self, page, errors=None, failed_assets=None):
        self.page = page
        # Whatever the page itself reported. A game that never renders is usually a page
        # error, and a harness that cannot say why is a harness that cannot be debugged.
        self.errors = errors if errors is not None else []
        # Asset requests that never completed. The static server drops connections under a
        # burst, and a page that lost `application.js` looks completely normal — it has its
        # elements, its other scripts and no error of its own — while never dealing a tile.
        self.failed_assets = failed_assets if failed_assets is not None else []

    async def evaluate(self, js):
        return await self.page.evaluate(js)

    async def press(self, key):
        await self.page.keyboard.press(key)

    async def goto(self, url):
        async with NAVIGATION_GATE:
            # The ledger covers one load: what failed on the previous page is not evidence
            # about this one.
            del self.failed_assets[:]
            await self.page.goto(url, wait_until="load")
            await asyncio.sleep(0.05)


class BrowserSession:
    def __init__(self, headless=False, cdp=None, url=None, viewport=(760, 980),
                 position=(60, 60)):
        self.headless = headless
        self.cdp = cdp
        self.url = url or labpaths.GAME_URL
        self.viewport = viewport
        self.position = position
        self.tab = None
        self.mode = ""
        self._playwright = None
        self._manager = None
        self._browser = None
        self._owned = False

    async def start(self):
        from playwright.async_api import async_playwright

        self._manager = async_playwright()
        self._playwright = await self._manager.__aenter__()
        if self.cdp:
            self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp)
            self._owned = False
            context = self._browser.contexts[0] if self._browser.contexts else \
                await self._browser.new_context()
            page = self._pick_page(context)
            self.mode = "cdp"
        else:
            # A headed window that a human pushes behind another window must keep rendering.
            # The game actuates inside requestAnimationFrame, so an occluded window that
            # Chromium stops compositing never deals its tiles and never saves its grid.
            args = ["--window-size=%d,%d" % (self.viewport[0] + 60, self.viewport[1] + 120),
                    "--window-position=%d,%d" % self.position,
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-background-timer-throttling",
                    "--disable-features=CalculateNativeWinOcclusion"]
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless, args=args)
            self._owned = True
            context = await self._browser.new_context(
                viewport=None if not self.headless else {"width": self.viewport[0],
                                                        "height": self.viewport[1]})
            page = await context.new_page()
            self.mode = "headless" if self.headless else "headed"
        await page.add_init_script(RNG_JS)
        await page.add_init_script(RENDER_JS)
        await self._paint_default_background(page)
        errors = []
        failed_assets = []

        def note_failure(request):
            failure = request.failure or "failed"
            if request.resource_type in ("script", "stylesheet", "document"):
                failed_assets.append("%s (%s)" % (request.url.rsplit("/", 1)[-1], failure))

        page.on("pageerror", lambda exc: errors.append("pageerror: %s" % str(exc)[:400]))
        page.on("console", lambda msg: errors.append("console.%s: %s" % (msg.type, msg.text[:300]))
                if msg.type in ("error", "warning") else None)
        page.on("requestfailed", note_failure)
        if not self.headless and not self.cdp:
            await page.bring_to_front()
        self.tab = Tab(page, errors, failed_assets)
        return self.tab

    async def _paint_default_background(self, page):
        """Make the page's default canvas the game's own colour instead of white.

        Every game is a fresh navigation, and Chromium paints its default background — white
        — for the moment before the document has any style. On a game that runs for minutes
        that is a white flash per game, which is exactly what a demo does not want. The
        override is cosmetic and best-effort: a browser that does not support it simply keeps
        the flash.
        """
        try:
            session = await page.context.new_cdp_session(page)
            await session.send("Emulation.setDefaultBackgroundColorOverride",
                               {"color": GAME_BACKGROUND})
        except Exception:
            pass

    def _pick_page(self, context):
        host = self.url.split("//")[-1].split("/")[0]
        for page in context.pages:
            if host in page.url:
                return page
        return context.pages[0] if context.pages else context.new_page()

    async def close(self):
        # An attached browser belongs to someone else: disconnect, never close it.
        if self._browser is not None and self._owned:
            await self._browser.close()
        if self._manager is not None:
            await self._manager.__aexit__(None, None, None)
        self._browser = None
        self.tab = None

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *_exc):
        await self.close()
