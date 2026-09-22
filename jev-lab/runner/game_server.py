"""Make sure something is serving the 2048 page, starting a server only if needed.

`run.py` and `benchmark.py` assume the game is already being served, because in the
development environment a long-lived process owns port 8792. Someone who has just cloned
this repository has no such process, and "run one command and watch" should not first
require them to read a paragraph about static servers.

If the URL already answers, nothing is started and nothing is stopped. If it does not, a
`python3 -m http.server` is spawned on the URL's port, rooted at the game's directory, and
terminated on the way out — only the one we started.
"""

import contextlib
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import labpaths  # noqa: F401


def is_serving(url, timeout=1.5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _port_is_free(host, port):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) != 0


def _wait_for(url, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_serving(url):
            return True
        time.sleep(0.15)
    return False


@contextlib.contextmanager
def ensure_game_server(url=None, root=None):
    """Yield the server process we started, or None when one was already running."""
    url = url or labpaths.GAME_URL
    root = root or labpaths.REPO
    if is_serving(url):
        yield None
        return

    parts = urlsplit(url)
    host = parts.hostname or "127.0.0.1"
    port = parts.port or 80
    if not _port_is_free(host, port):
        raise RuntimeError("something is listening on %s:%d but %s does not answer"
                           % (host, port, url))
    if not os.path.isdir(root):
        raise RuntimeError("the game directory is missing: %s" % root)

    print("starting the 2048 static server on %s:%d (root %s)" % (host, port, root),
          flush=True)
    process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", host,
         "--directory", root],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not _wait_for(url):
            raise RuntimeError("the static server did not answer on %s" % url)
        yield process
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
