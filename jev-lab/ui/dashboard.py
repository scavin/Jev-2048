"""The jev-lab dashboard: a local, stdlib-only HTTP server over the runner's JSON files.

The runner is a separate process, and the two only ever meet through three files in this
directory: ``live_state.json`` (runner writes, dashboard reads), ``control.json``
(dashboard writes, runner reads) and ``live.jpg`` (runner writes, dashboard serves).
Nothing is cached — every request re-reads the file, so a stalled runner can never look
alive.

Run it standalone with ``python ui/dashboard.py --port 8799``; the interactive runner
imports :class:`Dashboard` and serves the same page from a daemon thread.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import labpaths  # noqa: F401  (project root + reused modules on sys.path)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STATE_PATH = os.path.join(HERE, "live_state.json")
DEFAULT_CONTROL_PATH = os.path.join(HERE, "control.json")
DEFAULT_SCREENSHOT_PATH = os.path.join(HERE, "live.jpg")

GAME_URL = os.environ.get("GAME_URL", "http://127.0.0.1:8792/index.html")
# The page is static, but the game URL is environment-specific; the server substitutes it.
GAME_URL_TOKEN = "__GAME_URL__"

SPEEDS = ("1", "5", "20", "max")
DEFAULT_SPEED = "5"
# `command` is a level the runner holds, not a one-shot. A "step" means "stay paused, but
# spend one of the pending steps", so it lands on disk as `pause` plus a bigger budget.
COMMANDS = {
    "run": ("run", 0),
    "start": ("run", 0),
    "reset": ("reset", 0),
    "pause": ("pause", None),
    "step": ("pause", 1),
}
STATIC_FILES = {
    "/dashboard.js": ("dashboard.js", "application/javascript; charset=utf-8"),
    "/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
}
LOG_TAIL_BYTES = 256 * 1024
MAX_LOG_LIMIT = 5000


def _read_json(path):
    """The file's JSON, or ``None`` when it is missing or not (yet) valid JSON."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _write_json_atomic(path, payload):
    """Write ``payload`` through a temp file in the same directory, then rename it."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    temporary = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _tail_lines(path, limit):
    """The last ``limit`` lines of a text file, reading only its tail."""
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        start = max(0, size - LOG_TAIL_BYTES)
        handle.seek(start)
        data = handle.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    if start:
        lines = lines[1:]  # the first line was cut mid-way
    return lines[-limit:]


class _Handler(BaseHTTPRequestHandler):
    server_version = "jev-lab-dashboard"
    protocol_version = "HTTP/1.1"

    # Request logging would drown the recording; real errors still reach stderr.
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):  # noqa: N802 (http.server naming)
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        if route == "/":
            self._serve_page()
        elif route in STATIC_FILES:
            self._serve_static(route)
        elif route == "/api/state":
            self._serve_state()
        elif route == "/api/control":
            self._serve_control()
        elif route == "/api/log":
            self._serve_log(parse_qs(parsed.query))
        elif route == "/live.jpg":
            self._serve_screenshot()
        else:
            self._send_plain(404, "not found")

    def do_POST(self):  # noqa: N802 (http.server naming)
        route = urlparse(self.path).path.rstrip("/") or "/"
        if route != "/api/control":
            self._send_plain(404, "not found")
            return
        body = self._read_body()
        if body is None:
            self._send_plain(400, "body must be a JSON object")
            return

        current = _read_json(self.server.control_path) or {}
        if not isinstance(current, dict):
            current = {}
        command = current.get("command")
        if command not in COMMANDS:
            command = "pause"
        speed = current.get("speed")
        if speed not in SPEEDS:
            speed = DEFAULT_SPEED
        pending = max(0, _as_int(current.get("pending_steps"), 0))

        requested = body.get("command")
        if requested is not None:
            if not isinstance(requested, str) or requested not in COMMANDS:
                self._send_plain(400, f"command must be one of {sorted(COMMANDS)}")
                return
            command, grant = COMMANDS[requested]
            if grant is None:
                pass  # pause keeps whatever budget the runner has not spent yet
            elif grant == 1:
                pending += 1
            else:
                pending = 0  # run / reset start a fresh budget

        requested_speed = body.get("speed")
        if requested_speed is not None:
            requested_speed = str(requested_speed)
            if requested_speed not in SPEEDS:
                self._send_plain(400, f"speed must be one of {list(SPEEDS)}")
                return
            speed = requested_speed

        payload = {
            "seq": max(0, _as_int(current.get("seq"), 0)) + 1,
            "command": command,
            "speed": speed,
            "pending_steps": pending,
            "updated_at": time.time(),
        }
        _write_json_atomic(self.server.control_path, payload)
        self._send_json(payload)

    # -- requests -------------------------------------------------------------------

    def _read_body(self):
        length = _as_int(self.headers.get("Content-Length"), 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return body if isinstance(body, dict) else None

    def _serve_page(self):
        try:
            with open(os.path.join(HERE, "dashboard.html"), "r", encoding="utf-8") as handle:
                page = handle.read()
        except OSError as error:
            self._send_plain(500, f"dashboard.html is unreadable: {error}")
            return
        self._send_bytes(200, page.replace(GAME_URL_TOKEN, self.server.game_url).encode("utf-8"),
                         "text/html; charset=utf-8")

    def _serve_static(self, route):
        name, content_type = STATIC_FILES[route]
        try:
            with open(os.path.join(HERE, name), "rb") as handle:
                body = handle.read()
        except OSError as error:
            self._send_plain(404, f"{name} is missing: {error}")
            return
        self._send_bytes(200, body, content_type)

    def _serve_state(self):
        state = _read_json(self.server.state_path)
        if isinstance(state, dict):
            self._send_json(state)
        elif os.path.exists(self.server.state_path):
            self._send_json({"available": False, "error": "live_state.json is not valid JSON"})
        else:
            self._send_json({"available": False})

    def _serve_control(self):
        control = _read_json(self.server.control_path)
        if isinstance(control, dict):
            self._send_json(control)
        else:
            self._send_json({"available": False})

    def _serve_log(self, query):
        limit = _as_int((query.get("limit") or ["200"])[0], 200)
        limit = min(max(limit, 1), MAX_LOG_LIMIT)
        state = _read_json(self.server.state_path)
        log_path = state.get("log_path") if isinstance(state, dict) else None
        if not isinstance(log_path, str) or not log_path:
            self._send_json({"lines": []})
            return
        try:
            raw_lines = _tail_lines(log_path, limit)
        except OSError:
            self._send_json({"lines": []})
            return
        lines = []
        for raw in raw_lines:
            if not raw.strip():
                continue
            try:
                lines.append(json.loads(raw))
            except ValueError:
                continue
        self._send_json({"lines": lines})

    def _serve_screenshot(self):
        try:
            with open(self.server.screenshot_path, "rb") as handle:
                body = handle.read()
        except OSError:
            self._send_plain(404, "no screenshot yet")
            return
        self._send_bytes(200, body, "image/jpeg")

    # -- responses ------------------------------------------------------------------

    def _send_json(self, payload):
        self._send_bytes(200, json.dumps(payload).encode("utf-8"), "application/json")

    def _send_plain(self, status, message):
        self._send_bytes(status, message.encode("utf-8"), "text/plain; charset=utf-8")

    def _send_bytes(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, state_path, control_path, screenshot_path, game_url):
        self.state_path = state_path
        self.control_path = control_path
        self.screenshot_path = screenshot_path
        self.game_url = game_url
        try:
            super().__init__(address, _Handler)
        except OSError as error:
            raise RuntimeError(
                f"dashboard cannot bind {address[0]}:{address[1]}: {error}") from error


class Dashboard:
    """Serve the lab UI from a daemon thread. One instance owns one port."""

    def __init__(self, port=8799, state_path=None, control_path=None,
                 screenshot_path=None, host="127.0.0.1"):
        self.host = host
        self.port = int(port)
        self.state_path = state_path or DEFAULT_STATE_PATH
        self.control_path = control_path or DEFAULT_CONTROL_PATH
        self.screenshot_path = screenshot_path or DEFAULT_SCREENSHOT_PATH
        self._server = None
        self._thread = None

    @property
    def url(self):
        return f"http://{self.host}:{self.port}/"

    def start(self):
        """Bind and serve; returns the URL. Raises ``RuntimeError`` if the port is taken."""
        if self._server is not None:
            return self.url
        server = _Server((self.host, self.port), self.state_path, self.control_path,
                         self.screenshot_path, GAME_URL)
        self.port = server.server_address[1]
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever,
                                        name="jev-lab-dashboard", daemon=True)
        self._thread.start()
        return self.url

    def stop(self):
        server, self._server = self._server, None
        thread, self._thread = self._thread, None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve the jev-lab dashboard.")
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--state", default=None, help="path to live_state.json")
    parser.add_argument("--control", default=None, help="path to control.json")
    parser.add_argument("--screenshot", default=None, help="path to live.jpg")
    args = parser.parse_args(argv)

    dashboard = Dashboard(port=args.port, host=args.host, state_path=args.state,
                          control_path=args.control, screenshot_path=args.screenshot)
    url = dashboard.start()
    print(f"jev-lab dashboard on {url}", flush=True)
    if not os.path.exists(dashboard.state_path):
        print(f"waiting for a runner: {dashboard.state_path} does not exist yet", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        dashboard.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
