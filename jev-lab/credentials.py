"""Where the TypeSafe key lives, and how it is stored.

Deliberately not inside the repository: the game is served by a static server rooted at the
repository, so a key in the tree would be one URL away from being public. Deliberately not in
the control channel either: the runner publishes state derived from it to the browser, and a
file the panel reads is a file that leaks.

The key itself is only ever written. Callers ask :func:`status` whether one exists, which is
all the panel needs to draw its card, and nothing here returns the key to a browser.
"""

import os
from pathlib import Path

import labpaths  # noqa: F401  (puts the reused jev-test modules on sys.path)

from jev_client import load_env  # noqa: E402

# Windows keeps per-user configuration in LOCALAPPDATA; everything else follows the XDG rule.
_CONFIG_HOME = os.environ.get("LOCALAPPDATA" if os.name == "nt" else "XDG_CONFIG_HOME")
CONFIG_HOME = Path(_CONFIG_HOME).expanduser() if _CONFIG_HOME else Path.home() / ".config"
KEY_FILE = CONFIG_HOME / "jev-2048" / "credentials.env"
ENV_NAME = "TYPESAFE_API_KEY"


def load():
    """Read the saved key into the environment without clobbering what is already set."""
    load_env(str(KEY_FILE))


def configured():
    """Whether a key is available, from the environment or from the saved file."""
    if os.environ.get(ENV_NAME, "").strip():
        return True
    load()
    return bool(os.environ.get(ENV_NAME, "").strip())


def saved():
    """Whether the saved file itself holds a key. Never returns the key."""
    try:
        lines = KEY_FILE.read_text().splitlines()
    except OSError:
        return False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == ENV_NAME and value.strip().strip('"').strip("'"):
            return True
    return False


def status():
    """What the panel is allowed to know: that a key exists, and whether it is on disk."""
    return {"configured": configured(), "saved": saved()}


def save(key):
    """Write the key owner-only, outside the repository. Returns the path it went to."""
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        KEY_FILE.parent.chmod(0o700)
    descriptor = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        if os.name != "nt":
            os.fchmod(handle.fileno(), 0o600)
        handle.write("%s=%s\n" % (ENV_NAME, key))
    return KEY_FILE
