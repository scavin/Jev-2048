**中文文档 → [readme-cn.md](readme-cn.md)**

# Jev-2048 — a 2048 testbed for one question

A harness experiment, not a 2048 bot.

The game is the upstream [2048](https://github.com/gabrielecirulli/2048) by Gabriele Cirulli,
MIT-licensed and kept as-is — its own credits are in [LICENSE.txt](LICENSE.txt) and
[README-2048.md](README-2048.md). Everything under `jev-lab/` is the experiment added on top:
it does not reimplement the game and does not touch its files, and drives it from the outside,
through the rendered DOM and the keyboard, exactly as a human would.

The brief this was built against is kept in [prompt.md](prompt.md) (Chinese): it is what the
repository is answering, and it is worth reading next to §10 to see what was asked for and
what the data actually said.

The model never changes. Every jev mode in here is the same model, the same endpoint, the
same rules text and the same four candidate labels. The only thing that changes is **what
the harness shows it**:

| mode | the state handed to jev |
|---|---|
| `jev-board` | the 4×4 board, nothing else |
| `jev-state` | + score, max tile, empties, last move, recent moves, step, invalid attempts |
| `jev-history` | + the last 16 actions, recent board digests, how often this shape has appeared |
| `jev-features` | + the harness's own one-ply simulation of all four directions |
| `jev-state-history` | `jev-state` **and** `jev-history` together |

The fifth condition exists because the four required modes do not compare cleanly. Mode 3 is
specified as the board plus history, so moving from mode 2 to mode 3 adds history *and drops
mode 2's counters* — two changes at once. `jev-state-history` holds the counters fixed and
adds history on top, which is what isolates the effect of history itself.

Three deterministic baselines (`random`, `greedy`, `heuristic`) run the same games so the
jev numbers have something to be compared against.

The question the whole thing exists to answer:

> As the harness hands jev more of the work, where does its ability stop improving — and at
> what point does more context stop substituting for planning?

Nothing in this repository encodes an expected winner. The comparison table is generated
from the logs; if a jev mode loses to `greedy`, the table says so.

---

## 0. Getting started

### Download, then launch

Install **Python 3.10+** from [python.org](https://www.python.org/downloads/) if needed.
Fork this repository, then clone **your fork** or download and extract its ZIP.
Open a terminal in the extracted repository (the directory containing `start.py`):

```bash
python3 start.py
```

On Windows, use `py -3 start.py`. An interactive desktop and internet access are required.
The launcher automatically:

1. Creates `.venv/` inside the project and installs missing Python dependencies.
2. Downloads Chromium into `.jev/browsers/` and checks that it can launch.
3. Downloads the Jev client at pinned revision `1231850a0bf1a0c0341fe408ef1668dbbfdfac46`
   into `.jev/`. Git and local model weights are **not** required.
4. Asks for your **TypeSafe API key**, with input hidden. You must obtain a real key
   from [TypeSafe](https://typesafe.ai); API usage may incur charges.
5. Starts the game server, opens a **visible game window** and the live dashboard, and
   lets `jev-features` play one game after another until you stop it.

The launcher asks before saving a key. If you answer `y`, it saves plaintext **outside the
repository**, so the game's static server cannot serve it: `$XDG_CONFIG_HOME/jev-2048/credentials.env`
(default `~/.config/jev-2048/credentials.env`) on macOS/Linux, or
`%LOCALAPPDATA%\\jev-2048\\credentials.env` on Windows. The prompt shows the exact path.
macOS/Linux permissions are owner-only; Windows follows your user profile's ACLs.
Do not share this file; delete it to forget the key. An exported `TYPESAFE_API_KEY` takes
precedence, followed by the saved key and then `$JEV_REPO/.env`.
Keys supplied through those existing sources are not copied.

### Subsequent launches

Run the **same command**, `python3 start.py`, from the repository root. Existing dependencies,
Chromium and the Jev client are reused; no activation or `export` is needed if you saved
the key. If you declined to save it, enter it again or provide it through the environment.

### Setup without playing

```bash
python3 start.py --setup-only
```

This installs/checks the environment without requesting a key or calling the model API.
Python itself is not installed or changed. No global pip installs or automatic `sudo`
commands are run. On Linux, missing browser system libraries may require an administrator;
the launcher prints the command to run instead of installing them silently.

Downloads require access to PyPI, GitHub and Playwright's browser distribution.
Playing Jev also requires access to `api.typesafe.ai`. Setup checks local dependencies,
**not** remote key validity or available API credit; authentication/network errors can
still occur when the first decision is requested.

Advanced: set `JEV_REPO` to use an existing client checkout, or `PLAYWRIGHT_BROWSERS_PATH`
to reuse a browser cache. The launcher does not modify the supplied Jev checkout.
`demo.py` remains available for an environment you manage yourself. Examples elsewhere
using `python` assume that environment is active and the working directory is `jev-lab/`.
`demo.py` starts/stops only its own game server; `run.py` and `benchmark.py` require a
server that is already running.

Example output (using a short step limit):

```
  game 1 finished: max_steps after 25 moves, score 56, max tile 8
    best 56 (game 1, jev-board) · 1 played · avg 56 · 256+ 0/1
  game 2 finished: max_steps after 25 moves, score 112, max tile 16
    best 112 (game 2, jev-features) · 2 played · avg 84 · 256+ 0/2
```

### Stop it

Ctrl-C, or just close the game window — both close the log, shut down the browser and print the
summary. A game interrupted halfway keeps the moves it actually made.

### Then try

```bash
python3 start.py --mode jev-board              # the failure case: one direction, forever
python3 start.py --mode jev-features --speed 1 # slow down to read each decision
python3 start.py --mode jev-state,jev-features # alternate modes
python3 start.py --mode random                # no API key or Jev client needed
python3 start.py --max-steps 0                 # let every game run to its own end
```

### What to expect

Pace, so nothing looks broken: the model takes ~350 ms per move, and an illegal move costs
another ~350 ms while the harness waits for a page that will not change. So a `jev-features`
game of ~250 moves runs about three minutes; `jev-board` never dies on its own and only ends
at `--max-steps`. `--speed 1` is for watching one decision; `--speed max` is for leaving it on
in the background.

Two things about what you see on screen:

* **The window does not flash, and does not stutter.** Capturing a *visible* window forces
  Chromium to re-raster its surface, which reads as the whole window blinking — and the panel
  used to ask for a capture either side of every move, so the blink was synchronised with the
  moves and cost about a tenth of a second each. When the window is visible there is nothing
  to mirror, so **no screenshot is taken at all**: the panel draws the board from the data
  instead, and the game runs noticeably faster for it. `--shots` forces the mirror on anyway
  if you want to record the panel; `--no-shots` forbids it. Verified: a headed run makes zero
  screenshot calls and never writes `ui/live.jpg`; a headless one still mirrors.
* **No white flash between games either.** Every game is a fresh navigation, and Chromium
  paints its own default background — white — for the moment before a document has any style.
  The session overrides that default to the game's own `#faf8ef` through CDP, so a reload
  looks like the game rather than a white blink. Measured: a blank page renders
  `(250, 248, 239)` instead of `(255, 255, 255)`.

With `--no-dashboard` there is no panel at all, and the game window is the only thing on
screen.

---

## 1. What is reused, and what is not

Nothing about 2048 is reimplemented. The game is the upstream
[gabrielecirulli/2048](https://github.com/gabrielecirulli/2048) already in this repository,
served as static files:

```bash
# from the repository root; `demo.py` does this for you if you skip it
python3 -m http.server 8792 --bind 127.0.0.1
```

Reused as-is:

* **`game-test/game_client.py`** — the black-box page client. It reads the rendered
  `.tile-container .tile` elements, the score element and the `gameState` the page persists,
  and it clicks the game's own restart anchor through a real pointer sequence. No game
  internals are imported, so a bug in `GameManager` cannot hide behind the harness reading
  the same object graph.
* **`game-test/reference2048.py`** — an independent rules engine, already used in this repo
  as a differential oracle against the page. The lab uses it as its simulator, so "the
  harness thinks this move is legal" and "the page agrees" stay two separate statements.
* **`jev-test/jev_client.py`** — the loader that imports `jev_ultrafast/model.py` without
  pulling in the browser agent.
* **`browser-use/jev-ultrafast`** — `model.post_json` and `model.validate_choice`. Every
  decision in this lab travels the same two functions the shipped browser agent uses.

Added by the lab: the seeded browser session, the state builders, the baselines, the failure
detectors, the metrics, the dashboard and the runners.

### How the page is controlled

Arrow keys. The game's own `KeyboardInputManager` maps `ArrowUp/Right/Down/Left` to the four
moves, so the harness presses a key exactly as a human would:

| what the lab needs | how it gets it |
|---|---|
| board | the page's own persisted `gameState`, cross-checked against the rendered tiles |
| score | `.score-container` text (the `+8` animation span is stripped) |
| game over | the visible `.game-message` text, plus the simulator's own dead-board verdict |
| new game | click `.restart-button`; on a win, click `.keep-playing-button` to continue |
| one move | `ArrowUp` / `ArrowRight` / `ArrowDown` / `ArrowLeft` |

Reads wait for two agreeing snapshots, and the board itself is taken from the page's own
persisted `gameState`, falling back to the rendered tiles. That ordering matters: the game
writes `gameState` synchronously and paints the tiles one frame later, so a moved tile keeps
its old position class for a frame. Reading the painted tiles as the primary source would
occasionally report the position before the move — with the score already updated — on a
machine loaded enough for a frame to outlast the read interval. The tiles stay in the loop as
the cross-check: a merged cell holds three elements and `game_client` refuses to guess there,
and a difference between the two sources is recorded as `dom_behind_model` on the step.

Verified by differential test: 135 consecutive moves across three seeded games, every
observed board equal to the reference slide plus exactly one spawned 2 or 4, with an exact
score delta.

Two harness-side behaviours need stating because they are not obvious from the game.

**A frame fallback.** The game builds its `GameManager` inside a `requestAnimationFrame` and
renders every move inside one, so a headed window the compositor has stopped painting would
freeze the game entirely — it would never deal its first tiles. The browser session therefore
wraps `requestAnimationFrame` with a timer fallback that fires only when a real frame is more
than 250 ms late. A visible window behaves exactly as before; an occluded one keeps playing
instead of silently stalling. This changes no game rule and no random draw.

**No white flash on reload.** Chromium paints its own default background — white — for the
moment before a document has any style, and every game is a fresh navigation. The session
sets that default to the game's own `#faf8ef` through CDP, so the reload is invisible rather
than a white blink. Cosmetic and best-effort: a browser that does not support the override
simply keeps the flash.

**No capture of a window someone is watching.** `page.screenshot()` on a visible window
forces a surface re-raster, which flashes the whole window; asking for one either side of
every move made the flash look like part of the game and cost ~100 ms per move. The runner
therefore mirrors the window only when it is hidden (`--headless`), and the panel says so and
draws the board from the data instead. `--shots` / `--no-shots` override that.

**Serialized page loads.** The 2048 page is served by `python3 -m http.server`, which speaks
HTTP/1.0: one connection per file, closed as soon as the response is written, with a listen
backlog of 5. A page needs about a dozen files, so several browsers loading it at the same
instant overflow that backlog and the page arrives *without some of its scripts* —
`net::ERR_CONNECTION_RESET`, no tiles, and no error of the game's own. Page loads are
therefore serialized process-wide, and a load that loses an asset is detected immediately and
reloaded rather than waited on. With that in place, eight concurrent sessions open games with
zero failures; without it, roughly a third of concurrent games aborted.

---

## 2. The one variable

Every mode sends the same `instructions` block and the same four candidate labels. Only
`state` and `criteria` differ.

```text
goal:  Avoid game over and reach the highest tile possible.
rules: 2048 rules: a move slides every tile toward that edge. Two tiles of equal value
       that collide merge into one tile of their sum, and the score increases by that sum.
       After a move that changes the board, one new tile of value 2 or 4 appears in an
       empty cell. The game is over when no direction changes the board.
```

All four directions are always offered, including illegal ones. Legality is information the
harness may or may not supply — which is what makes the invalid-move rate a real
measurement rather than a constant zero.

### Mode 1 — `jev-board`

```text
Current 2048 board:

2 4 8 16
0 2 4 8
0 0 2 4
0 0 0 2

Choose one move:

UP
DOWN
LEFT
RIGHT

Goal:
Avoid game over and reach the highest tile possible.
```

### Mode 2 — `jev-state`

```text
Board:
2 4 8 16
0 2 4 8
0 0 2 4
0 0 0 2

Score: 4820
Max tile: 16
Empty cells: 6
Last move: DOWN
Recent moves:
DOWN, LEFT, DOWN, RIGHT, DOWN
Step: 183
Recent invalid moves: RIGHT x2
Repeated move pattern: no
```

### Mode 3 — `jev-history`

```text
Board:
2 4 8 16
0 2 4 8
0 0 2 4
0 0 0 2

Recent actions:
LEFT, RIGHT, LEFT, RIGHT, LEFT, RIGHT, DOWN, UP, DOWN, LEFT, DOWN, RIGHT, DOWN

Recent board states:
  1. hash=a1b2c3d4e5f6 score=4200 max=16 empty=7

Current board pattern seen before: 3 times
Recent action pattern: UP, DOWN, LEFT, DOWN, RIGHT, DOWN
Invalid RIGHT attempts recently: 2
```

The history mode states facts and stops there. It never says what to do about a repeat.

### Mode 4 — `jev-features`

The harness simulates each direction one ply ahead and reports measurements of the board it
produces. One ply only: no two-step lookahead, no search, no rollout.

```text
DOWN:
  valid: true
  score_gain: 0
  merge_count: 0
  empty_cells_after: 6
  max_tile_after: 16
  max_tile_in_corner: true
  corner_preserved: true
  monotonicity: 1.0
  smoothness: -6.0
  changed_cells: 10
  mobility: 3
  board_entropy: 1.846
```

Feature definitions (all deterministic, all on the slid board, the spawn is never guessed):

* `monotonicity` ∈ [0, 1] — for each row and column, the best one-way run divided by that
  line's total variation. 1.0 means every line runs one way.
* `smoothness` ≤ 0 — negative total `|log2` gap`|` between adjacent non-empty tiles.
* `mobility` — how many directions still change the board.
* `board_entropy` — Shannon entropy in bits of the tile-value distribution.
* `corner_preserved` / `max_tile_in_corner` — whether the largest tile is in a corner.
  Only a **unique** largest tile counts: early boards hold several 2s and 4s, and calling
  one of them "the big tile" would invent a corner strategy the player has not started.
* `changed_cells` — cells that differ from the board before the move.

### Mode 5 — `jev-state-history`

Mode 2's block followed by mode 3's block, with nothing else changed. Same two blocks, same
order, no extra advice:

```text
Score: 4820
Max tile: 16
Empty cells: 6
Last move: DOWN
Recent moves:
DOWN, LEFT, DOWN, RIGHT, DOWN
Step: 183
Recent invalid moves: RIGHT x1
Repeated move pattern: no

Recent actions:
LEFT, RIGHT, LEFT, RIGHT, LEFT, RIGHT, DOWN

Recent board states:
  1. hash=a1b2c3d4e5f6 score=4200 max=16 empty=7

Current board pattern seen before: 3 times
Recent action pattern: RIGHT, LEFT, RIGHT, LEFT, RIGHT, DOWN
```

---

## 3. The baselines

| mode | rule |
|---|---|
| `random` | uniform over the legal directions, from its own seeded generator |
| `greedy` | largest immediate `score_gain`; ties to more empty cells, then a fixed order |
| `heuristic` | argmax of a hand-written evaluation of the board one move ahead |

The heuristic uses nneonneo's published weights for empty cells (2.7), monotonicity (1.0) and
smoothness (0.1), plus three additions: a corner bonus of `log2(max tile)`, 0.6 per merge
available after the move, and 1.0 per legal direction. None of these were tuned on this
benchmark, and none of them are visible to any jev mode.

All three baselines only ever pick a legal direction, so their invalid-move rate is zero by
construction.

---

## 4. Who decides what

The harness may read the board, keep history, compute deterministic statistics, simulate one
ply, detect loops and failures, write logs, and press arrow keys.

The harness may not choose the move. There is no code path that turns a failure tag, a
heuristic score or a loop detection into a direction. Tags are recorded next to the step that
earned them and nothing else. When the model's answer cannot be validated, the game is
recorded as `aborted` with the reason — it is never patched with a substitute move.

---

## 5. Reproducibility

`benchmark.py --seed 123` and `run.py --seed 123` give the same spawns.

The game spawns tiles with `Math.random`, twice per new tile (the value, then the cell). The
browser session installs an init script that replaces `Math.random` with a seeded
deterministic stream, reading the seed from the page's own query string:

```js
const raw = new URLSearchParams(location.search).get("seed");
let state = (Number(raw) >>> 0) || 1;
Math.random = () => { /* mulberry32 */ };
```

Every game navigates to `index.html?seed=N`, and the same init script removes the page's
saved game at document start, so the load always deals a fresh pair of tiles from the
beginning of the stream. A whole game is therefore a function of `(seed, action sequence)`.

Verified: the same seed produced **byte-identical boards, actions and scores** (a) over a
real Chrome attached by CDP and over a fresh headless Chromium, for ten moves, and (b) at
`--workers 1` and `--workers 5`, for five full games move by move.

**Limits, stated plainly.** The draw stream is positional, so two policies are aligned only
while they have spawned the same number of tiles:

* an illegal move spawns nothing, so a policy that wastes moves drifts out of alignment with
  one that does not;
* the cell is drawn as `floor(r × available_cells)`, so even at the same spawn index the
  chosen cell can differ if the two boards have different sets of empty cells.

Same seed therefore means "the same random stream in the same order", not "the same board
after every move". This is the strongest guarantee available without modifying the game's own
spawn code, which this project does not do. Within a mode, games are independent: game `i`
uses `seed + i`, and `--workers N` does not change any result.

---

## 6. Logging

One JSONL line per executed move, flushed as it is written.

```json
{
  "game_id": 12, "seed": 123, "step": 87, "mode": "jev-features",
  "board_before": [[2,4,8,16],[0,2,4,8],[0,0,2,4],[0,0,0,2]],
  "board_after":  [[0,0,0,16],[0,0,8,8],[0,4,4,4],[2,2,2,2]],
  "action": "down", "action_valid": true,
  "score_before": 1828, "score_after": 1836, "score_gain": 8, "score_gain_expected": 8,
  "max_tile": 256, "empty_cells": 5, "empty_cells_after": 6,
  "latency_ms": 43.0, "step_wall_ms": 78.2, "read_ms": 24.0,
  "recent_moves": ["down","left","down","right","down"],
  "board_hash": "0fcb3b167010", "state_hash": "9f2c1a77b3e5",
  "largest_corner": "tr", "largest_corner_after": null,
  "monotonicity": 0.61, "monotonicity_after": 0.88,
  "page_reacted": true,
  "decision_source": "jev-features",
  "jev_probabilities": {"up":0.08,"down":0.67,"left":0.19,"right":0.06},
  "jev_confidence": 0.41, "jev_attempts": 1, "jev_model": "jev-1.13.0",
  "jev_usage": {"input_tokens": 948, "output_tokens": 45},
  "prompt_preview": "...", "request_state": {"board": [[...]]},
  "features_after": {"up": {...}, "down": {...}, "left": {...}, "right": {...}},
  "failure_tags": []
}
```

`board_hash` is the exact position; `state_hash` is the same board canonicalised under the
eight rotations and mirrors, so "this shape again" is detectable even when the tiles have
moved around. `action_valid` is the simulator's verdict; `page_reacted` is what the page
actually did. When those two disagree, the step is tagged `harness_desync` — that would mean
the harness is wrong about the game, not that jev is.

The three logs behind the results in §9 are committed gzipped, because every number in that
table and in §10 is derived from them:

```bash
cd jev-lab
for f in logs/*.jsonl.gz; do gzip -dc "$f" | head -1 | python3 -m json.tool; done   # one step
gzip -dc logs/jev.jsonl.gz | wc -l                                                  # 11050 steps
```

---

## 7. Failure detectors

Eight checks, all of them readable from the harness side alone. They mark steps and never
change one.

| tag | fires when |
|---|---|
| `alternating_loop` | two directions alternate for 6 moves (`L R L R L R`, `U D U D U D`) |
| `repeated_state` | the same shape, up to rotation and mirroring, appears 3 times in 20 moves |
| `invalid_repetition` | the same illegal direction is chosen twice within 10 moves |
| `corner_break` | the largest tile leaves a corner it had held for 5 moves |
| `space_collapse` | empties fall monotonically by 6+ over 10 moves and end at 2 or fewer |
| `greedy_trap` | 32+ points scored over 8 moves while monotonicity drops 0.15+ or space drops 4+ |
| `decision_stagnation` | the same direction 4 times running with no score and no legal effect |
| `harness_desync` | the simulator's legality verdict and the page's reaction disagree |

Each detector is verified to fire on a hand-built pattern of exactly that failure, and to stay
silent on a clean game.

---

## 8. Running it

```bash
cd jev-lab

# watch it play, forever (see §0)
python demo.py

# one game, visible browser, live panel
python run.py --mode jev-board
python run.py --mode jev-features --speed 1
python run.py --mode jev-history --cdp http://127.0.0.1:9222   # drive an existing Chrome
python run.py --mode jev-board --games 0                       # until stopped

# batch
python benchmark.py --mode random     --games 100 --headless
python benchmark.py --mode greedy     --games 100 --headless
python benchmark.py --mode heuristic  --games 100 --headless
python benchmark.py --mode jev-board    --games 100 --headless
python benchmark.py --mode jev-state    --games 100 --headless
python benchmark.py --mode jev-history  --games 100 --headless
python benchmark.py --mode jev-features --games 100 --headless

# all seven required modes in one pass, six games at a time
python benchmark.py --mode random,greedy,heuristic,jev-board,jev-state,jev-history,jev-features \
  --games 100 --seed 123 --headless --workers 6

# report from whatever summaries exist
python analysis/report.py
```

The browser is **headed by default**; `--headless` is only for batches. `--seed` fixes the
spawn stream, `--games N` sets the batch size, `--workers N` runs games concurrently (each
with its own tab and its own seed, so results do not depend on it).

`run.py` also starts the dashboard on `http://127.0.0.1:8799` and opens it in your own
browser. The panel shows the live board, the step, the score, max tile, empties, latency, the
model's probabilities per direction, the chosen move, recent moves, the failure checks, and —
in feature mode — the four directions' features. Start / Pause / Step / Reset / speed
1x·5x·20x·Max are there for stepping through a single decision.

If the model's probabilities are unavailable (every baseline), the panel says so rather than
drawing a bar. Nothing on the panel is invented.

---

## 9. Results

Three runs, same seed, same page, same rules text, same model. Every game navigates to
`index.html?seed=N` and the spawn stream is a function of `N` alone.

```bash
cd jev-lab

# baselines: uncapped, they finish on their own
python benchmark.py --mode random,greedy,heuristic --games 20 \
  --seed 123 --headless --workers 6 --max-steps 2000 --tag baseline

# the model: capped at 300 moves, because it does not reliably finish
python benchmark.py --mode jev-board,jev-state,jev-history,jev-features --games 12 \
  --seed 123 --headless --workers 4 --max-steps 300 --tag jev
python benchmark.py --mode jev-state-history --games 12 \
  --seed 123 --headless --workers 4 --max-steps 300 --tag jev-sh

python analysis/report.py results/baseline_summary.json results/jev_summary.json \
  results/jev-sh_summary.json
```

| Mode | Games | Scored | Abort% | Avg Score | Median | P90 | Max | Avg Steps | Max Tile | 256% | 512% | 1024% | 2048% | 4096% | Invalid% | Loop% | Repeat% | Corner% | Collapse% | Trap% | Stagnation% | Avg Lat ms | P50 ms | P95 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| random | 20 | 20 | 0.0 | 1010.0 | 922.0 | 1636.0 | 2160 | 112.5 | 100.8 | 5.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.00% | 0.49% | 0.00% | 0.40% | 0.36% | 3.78% | 0.00% | 0.0 | 0.0 | 0.0 |
| greedy | 20 | 20 | 0.0 | 2984.8 | 3040.0 | 4252.4 | 4584 | 260.5 | 211.2 | 65.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.00% | 2.55% | 0.00% | 1.55% | 0.02% | 0.96% | 0.00% | 0.0 | 0.0 | 0.0 |
| heuristic | 20 | 20 | 0.0 | 5814.2 | 5870.0 | 7748.0 | 12152 | 404.2 | 460.8 | 100.0 | 60.0 | 10.0 | 0.0 | 0.0 | 0.00% | 1.77% | 0.00% | 1.81% | 0.01% | 2.13% | 0.00% | 0.0 | 0.0 | 0.0 |
| jev-board | 12 | 12 | 0.0 | 22.7 | 18.0 | 49.6 | 72 | 300.0 | 6.7 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 97.25% | 0.00% | 96.28% | 0.00% | 0.00% | 0.00% | 96.25% | 432.8 | 337.4 | 902.2 |
| jev-state | 12 | 12 | 0.0 | 593.7 | 606.0 | 802.4 | 1004 | 86.6 | 64.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 7.03% | 0.96% | 2.12% | 0.29% | 0.58% | 4.72% | 0.10% | 519.3 | 392.4 | 1152.0 |
| jev-history | 12 | 12 | 0.0 | 462.3 | 458.0 | 685.6 | 1036 | 261.7 | 53.3 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 74.20% | 0.06% | 68.41% | 0.16% | 0.00% | 0.57% | 60.86% | 487.2 | 362.6 | 967.6 |
| jev-features | 12 | 12 | 0.0 | 3781.7 | 4282.0 | 4555.6 | 4564 | 272.6 | 373.3 | 91.7 | 50.0 | 0.0 | 0.0 | 0.0 | 0.00% | 0.86% | 0.00% | 2.57% | 0.03% | 1.86% | 0.00% | 425.5 | 354.4 | 779.0 |
| jev-state-history | 12 | 12 | 0.0 | 779.7 | 736.0 | 1182.8 | 1356 | 171.3 | 77.3 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 44.55% | 0.83% | 38.33% | 0.39% | 0.15% | 2.38% | 28.26% | 558.6 | 366.8 | 1216.1 |

Reading the table:

* **Games / Scored / Abort%** — a game the harness aborted (dropped connection, page that
  never loaded) is a truncated game, not a result, so it is excluded from the score, step and
  tile statistics and counted here instead. Both runs finished with **0% aborts**.
* **Avg Steps** is capped at 300 for every jev row and at 2000 for the baselines. The cap
  never bound a baseline game (the longest was 719 moves); it bound 12/12 of `jev-board`,
  7/12 of `jev-features`, 9/12 of `jev-history` and 3/12 of `jev-state-history`. A capped jev
  score is therefore a **lower bound**, and `jev-board`'s 300 moves produced a board with a
  largest tile of 4 in most games.
* **Invalid%** is the share of moves the game ignored, measured by the simulator and
  confirmed against the page's reaction. Every baseline is 0% by construction.
* **Loop% / Repeat% / Corner%** are per-step rates of the failure detectors; see §7.
* **Latency** is the model call. Baselines have none, so their latency is 0 by definition.

## 10. What did we learn about Jev?

Twelve questions, answered from the table above and from the per-step logs.

**1. Board only, how far does jev get?**
Nowhere. `jev-board` averages **22.7** with a largest tile of **6.7** — it usually never
merges anything at all. **97.2%** of its moves are illegal, and the average longest run of
one direction is **293.8 moves out of 300**. In most games it picks a direction and never
picks another: `LEFT 76%, RIGHT 24%, UP 0%, DOWN 0%`. It is 44× worse than random.

**2. Does explicit state help?**
Enormously. `jev-state` scores **593.7**, a 26× improvement, and the invalid rate falls from
97.2% to **7.0%**. But 593.7 is still **below random's 1010**. Being told the score, the
space, the last move and how many attempts were wasted turns an agent that cannot play into
an agent that plays badly.

**3. Does history break loops?**
No — it creates them. The specified history mode `jev-history` is *worse* than `jev-state`
(462.3 vs 593.7) with **74.2%** invalid moves and **68.4%** repeated-state steps. The
disentangling condition `jev-state-history` holds mode 2's counters fixed and adds history on
top: the score rises to **779.7**, but the invalid rate goes **7.0% → 44.6%**, the
repeated-state rate **2.1% → 38.3%**, and the longest single-direction run **3.7 → 20.2**.
History made jev more repetitive, not less. The higher score comes from the game lasting
longer (86.6 → 171.3 moves) — and it lasts longer partly *because* illegal moves freeze the
board. Score per legal move does not improve either — 7.37 for `jev-state`, 8.21 for
`jev-state-history`, 6.85 for `jev-history` — see question 7.

**4. How much does one-ply deterministic feature extraction buy?**
It is the only intervention that changes the kind of agent. `jev-features` scores **3781.7**:
**6.4×** mode 2, **167×** mode 1. The invalid rate goes to **0.0%**, it reaches 256 in
**91.7%** of games and 512 in **50.0%** — against 0% and 0% for every other jev mode.

**5. Is jev better than random?**
Only `jev-features` (3781.7 vs 1010). `jev-state` (593.7), `jev-history` (462.3) and
`jev-state-history` (779.7) are all below random, and `jev-board` (22.7) is far below it.
Three of the five conditions lose to a coin flip over the legal moves.

**6. Is jev better than greedy?**
Yes, in the feature-assisted condition: **3781.7 vs 2984.8**, reaching 256 in 91.7% of games
against 65.0%, and 512 in 50.0% against 0%. No other jev mode comes close to greedy.

**7. How far is jev from the traditional heuristic?**
`jev-features` reaches **65%** of the heuristic's average score (3781.7 vs 5814.2) and, with
the step cap in mind, that is a lower bound. The interesting number is efficiency per legal
move:

| policy | score per legal move | legal moves per game |
|---|---|---|
| heuristic | 14.38 | 404 |
| **jev-features** | **13.87** | 272 (capped) |
| greedy | 11.46 | 260 |
| random | 8.97 | 112 |
| jev-state-history | 8.21 | 95 |
| jev-state | 7.37 | 80 |
| jev-history | 6.85 | 68 |
| jev-board | 2.75 | 8 |

Per move, the feature-assisted mode is already at the heuristic's level. What it does not do
is survive: the heuristic plays 404 moves a game to reach 1024 in 10% of them, and the jev
modes run out of steps or out of board. **The gap is planning depth, not move quality.**

**8. Where does jev fail most?**
Two places, both visible in the logs. When it has to infer legality itself — 97.2% illegal
with the board alone, 74.2% with a history block, 44.6% with history added to state. And when
the context is a long list of past actions, which it treats as a pattern to continue: the
stagnation detector fires on 96.3% of `jev-board` steps, 60.9% of `jev-history` steps and
28.3% of `jev-state-history` steps, against 0.1% and 0.0% for `jev-state` and `jev-features`.

**9. Can jev use history to escape a local optimum?**
Not in this experiment. Every additional helping of history is associated with *longer*
fixation: longest single-direction run 3.7 moves with counters only, 20.2 with counters plus
history, 125.0 with history replacing the counters, 293.8 with the board alone.

**10. Is jev good at trading off several local metrics at once?**
Partly, and this design cannot fully separate the two effects. The feature block is the only
condition that beats a baseline, and its per-move efficiency matches the heuristic — so yes,
it can weigh monotonicity, smoothness, space and merge count well enough to play. But the
same block also carries `valid`, and once legality is spelled out the invalid rate is 0.0%.
How much of the 3781.7 is metric trade-off and how much is simply "someone told me which
moves are legal" is not separable here. A follow-up that drops `valid` from the block while
keeping the rest would settle it.

**11. Which information is worth having the harness compute?**
In order of measured value: **the one-ply simulation** (167× over the board alone, and the
only condition that beats a baseline); **the explicit counters** (26× over the board alone,
and they are nearly free); and, last, **the action history**, which at this length is worse
than nothing. The cheapest useful thing the harness can do is tell jev which moves are legal.

**12. Where does more context stop substituting for search?**
At roughly the greedy line. One ply of deterministic evaluation is enough to get jev from
"cannot play" to "as good as one-ply score greed, per move". It is not enough to reach 1024:
every jev mode except the feature-assisted one fails to get past a largest tile of 128, and
the feature-assisted one reaches 512 in half its games and 1024 in none. The heuristic's
advantage at 1024+ comes from playing three times as many moves, which is a property of the
position, not of any single move — and no amount of extra single-step context in this
experiment recovered it.

---

## 11. Layout

```text
.                          the upstream 2048 game (index.html, js/, style/, meta/)
├── start.py               automatic project setup and visible demo launcher
├── readme.md              this file            readme-cn.md  the Chinese version
├── README-2048.md         the upstream game's own readme
├── prompt.md              the brief this experiment was built against (Chinese)
├── game-test/             existing control code the lab reuses:
│                            game_client.py    black-box page client (DOM + localStorage)
│                            reference2048.py  independent rules engine, used as the simulator
│                            run_tests.py      the repo's own differential suite
├── jev-test/jev_client.py the loader for jev's own model.py, and the .env reader
└── jev-lab/               the experiment
    ├── game/              adapter (page control) · state (observation) · simulator (rules)
    ├── jev/               client (the only decision layer) · prompts (one builder per mode)
    ├── players/           random · greedy · heuristic · jev_board · jev_state · jev_history ·
    │                      jev_features · jev_state_history
    ├── analysis/          features · failure_detector · metrics · report
    ├── runner/            browser · game_server · game_loop · interactive · benchmark
    ├── ui/                dashboard (server + page)
    ├── logs/              per-step JSONL (gitignored)   results/  summary JSON + CSV
    ├── demo.py            watch it play, forever
    ├── run.py             one run, visible browser
    └── benchmark.py       batch, several modes
```

## 12. Requirements

Everything the lab imports beyond the standard library, and why it is needed. The commands
that install and configure all of it are in §0.

* **`playwright`** plus Chromium (`playwright install chromium`) — the browser session. The
  game is driven through a real browser, so there is no lighter path.
* **`httpx[http2]`** — the decision layer calls `model.post_json` from jev's own `model.py`,
  which builds an `httpx.Client(http2=True)`. Plain `httpx` gets as far as the first move and
  then raises an ImportError about the `h2` package; without httpx at all it is a
  `ModuleNotFoundError` on the same line.
* **Jev client source** — [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast).
  The launcher downloads a pinned revision and sets `JEV_REPO` automatically. To invoke the
  lab directly, set `JEV_REPO` to your own checkout; the lab reuses its `post_json` and
  `validate_choice` rather than reimplementing the request path.
* **`TYPESAFE_API_KEY`** — supplied as described in §0. The baselines need neither the key
  nor the Jev client, but still require Python, Playwright and Chromium.
* **The 2048 page** on `http://127.0.0.1:8792`. `demo.py` starts it for you; see §0.

Launcher verification on macOS: created a fresh project venv, installed dependencies,
downloaded Chromium and the pinned Jev client, and completed a real headed Jev game with
that installation. Also verified reuse of an existing Chromium cache, hidden key entry,
explicit saving outside the repository (mode 0600), and subsequent launches without an
install/download/key prompt. Short 8-step games restarted automatically; Ctrl-C exited
cleanly and stopped the owned servers. Missing-key and invalid `JEV_REPO` errors were
exercised. Windows/Linux instructions have not been runtime-tested.
