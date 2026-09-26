"""Install missing project dependencies, then watch Jev play in the new dashboard.

    python3 start.py                  # new dashboard; game runs in the background
    python3 start.py --retro          # original 2048 window only
    python3 start.py --setup-only     # install/check without asking for a key or playing
    python3 start.py --mode random    # no model or credentials required

All demo.py options are accepted. No system packages or administrator commands are run.
"""

import argparse
import getpass
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import venv
import zipfile

ROOT = Path(__file__).resolve().parent
ENV_DIR = ROOT / ".venv"
LOCAL = ROOT / ".jev"
# Keep secrets outside the repository served by the game's static HTTP server.
CONFIG_HOME = Path(os.environ.get("LOCALAPPDATA" if os.name == "nt" else "XDG_CONFIG_HOME")
                   or Path.home() / ".config").expanduser()
KEY_FILE = CONFIG_HOME / "jev-2048" / "credentials.env"
JEV_REVISION = "1231850a0bf1a0c0341fe408ef1668dbbfdfac46"
JEV_SOURCE = LOCAL / ("jev-ultrafast-" + JEV_REVISION)
# name -> (minimum, exclusive maximum or None, pip requirement). The versions this repository
# was verified against, as minimums: an install already inside the range is left untouched
# rather than replaced, and the browser check below covers the matching browser revision.
REQUIREMENTS = {
    "playwright": ((1, 63, 0), (2,), "playwright>=1.63.0,<2"),
    "httpx": ((0, 28, 1), (1,), "httpx[http2]>=0.28.1,<1"),
    "h2": ((4, 4, 1), None, "h2>=4.4.1"),
}


def say(message):
    print("[setup] " + message, flush=True)


def run_command(command):
    result = subprocess.run(command)
    if result.returncode:
        raise RuntimeError("Command failed (exit %d): %s" %
                           (result.returncode, subprocess.list2cmdline(command)))


def enter_environment():
    """Only the project venv receives pip installs, even when called from another venv."""
    if Path(sys.prefix).resolve() == ENV_DIR.resolve():
        return
    python = ENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        say("Creating project environment: %s" % ENV_DIR)
        try:
            venv.EnvBuilder(with_pip=True).create(ENV_DIR)
        except Exception as exc:
            raise RuntimeError("Cannot create .venv. Install Python with venv/ensurepip "
                               "support (on Debian/Ubuntu: python3-venv), then retry. %s" % exc) from exc
    command = [str(python), str(ROOT / "start.py"), *sys.argv[1:]]
    if os.name != "nt":
        os.execv(str(python), command)
    child = subprocess.Popen(command)
    try:
        code = child.wait()
    except KeyboardInterrupt:
        # The console delivers Ctrl-C to the child as well; let demo.py clean up.
        code = child.wait()
    raise SystemExit(code)


def _version_tuple(text):
    """Enough of a version parser to compare what pip reports against these minimums."""
    numbers = []
    for chunk in str(text).replace("-", ".").split("."):
        digits = ""
        for character in chunk:
            if character.isdigit():
                digits += character
            else:
                break
        numbers.append(int(digits) if digits else 0)
    return tuple(numbers)


def ensure_packages():
    missing = []
    present = []
    for name, (minimum, maximum, requirement) in REQUIREMENTS.items():
        try:
            reported = importlib.metadata.version(name)
            installed = _version_tuple(reported)
        except importlib.metadata.PackageNotFoundError:
            reported, installed = None, None
        if installed is None or installed < minimum or (maximum and installed >= maximum):
            missing.append(requirement)
        else:
            present.append("%s %s" % (name, reported))
    if present:
        say("Already installed, left alone: " + ", ".join(present))
    if missing:
        say("Installing (PyPI access required): " + ", ".join(missing))
        run_command([sys.executable, "-m", "pip", "install", *missing])


def ensure_browser():
    from playwright.sync_api import Error, sync_playwright

    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
    if executable.is_file():
        # Playwright's cache is shared with every other project on the machine, so a browser
        # that is already there is used as it is rather than downloaded a second time.
        say("Chromium already installed: %s" % executable)
    else:
        location = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "Playwright's default cache"
        say("Chromium is missing; installing it into %s" % location)
        run_command([sys.executable, "-m", "playwright", "install", "chromium"])
    try:
        with sync_playwright() as playwright:
            # No channel, and headless: the same launch the demo performs, headless shell included.
            browser = playwright.chromium.launch(headless=True)
            browser.close()
    except Error as exc:
        raise RuntimeError(
            "Chromium is installed but cannot start. Repair it with: %s -m playwright install "
            "chromium. On Linux, missing system libraries may require an administrator to run: "
            "%s -m playwright install-deps chromium. No sudo command was run automatically.\n%s"
            % (sys.executable, sys.executable, exc)) from exc
    say("Chromium launch check passed.")


def ensure_jev(override):
    target = Path(override).expanduser().resolve() if override else JEV_SOURCE
    if override:
        if not (target / "jev_ultrafast/model.py").is_file():
            raise RuntimeError("JEV_REPO has no jev_ultrafast/model.py: %s. "
                               "Correct or unset JEV_REPO to use the automatic download." % target)
    elif not target.is_dir():
        say("Downloading pinned Jev client %s (not model weights)." % JEV_REVISION[:12])
        url = "https://codeload.github.com/browser-use/jev-ultrafast/zip/" + JEV_REVISION
        with tempfile.TemporaryDirectory(prefix="download-", dir=LOCAL) as temporary:
            archive = Path(temporary) / "jev.zip"
            with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as out:
                shutil.copyfileobj(response, out)
            extracted = Path(temporary) / "source"
            with zipfile.ZipFile(archive) as zipped:
                for member in zipped.infolist():
                    destination = (extracted / member.filename).resolve()
                    if not destination.is_relative_to(extracted.resolve()):
                        raise RuntimeError("Unsafe path in Jev source archive")
                zipped.extractall(extracted)
            source = extracted / ("jev-ultrafast-" + JEV_REVISION)
            if not (source / "jev_ultrafast/model.py").is_file():
                raise RuntimeError("Downloaded Jev archive has no model client")
            source.rename(target)
    if not (target / "jev_ultrafast/model.py").is_file():
        raise RuntimeError("Incomplete Jev client at %s; remove that directory and retry." % target)
    os.environ["JEV_REPO"] = str(target)
    say("Jev client ready: %s" % target)


def configure_key():
    # Reuse the same .env reader and precedence as the demo: environment wins.
    sys.path.insert(0, str(ROOT / "jev-test"))
    from jev_client import load_env

    load_env(str(KEY_FILE))
    load_env()
    if os.environ.get("TYPESAFE_API_KEY", "").strip():
        say("Using configured TypeSafe API key (not displayed).")
        return
    if not sys.stdin.isatty():
        raise RuntimeError("TYPESAFE_API_KEY is missing. Run in a terminal to enter it, "
                           "or supply it through the environment.")
    print("A TypeSafe API key is required: https://typesafe.ai\n"
          "It will be sent to api.typesafe.ai for game decisions. API usage may incur charges.")
    key = getpass.getpass("TYPESAFE_API_KEY (hidden): ").strip()
    if not key or any(char in key for char in "\r\n"):
        raise RuntimeError("An API key is required; no game was started.")
    os.environ["TYPESAFE_API_KEY"] = key
    save = input("Save key in %s for future launches? Plaintext, outside the repository. "
                 "[y/N] " % KEY_FILE).strip().lower()
    if save in ("y", "yes"):
        if KEY_FILE.resolve().is_relative_to(ROOT):
            raise RuntimeError("Refusing to save a key inside the game's web root. "
                               "Choose a config directory outside the repository.")
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            KEY_FILE.parent.chmod(0o700)
        descriptor = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            if os.name != "nt":
                os.fchmod(handle.fileno(), 0o600)
            handle.write("TYPESAFE_API_KEY=" + key + "\n")
        say("Saved locally: %s. Delete this file to forget the key. "
            "On Windows, access is governed by your user profile's ACLs." % KEY_FILE)


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--setup-only", action="store_true", help="install/check, then exit")
    args, demo_args = parser.parse_known_args()
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 or newer is required: https://www.python.org/downloads/")
    enter_environment()
    LOCAL.mkdir(exist_ok=True, mode=0o700)
    ensure_packages()
    override = os.environ.get("JEV_REPO")
    target = Path(override).expanduser().resolve() if override else JEV_SOURCE
    os.environ["JEV_REPO"] = str(target)
    sys.path.insert(0, str(ROOT / "jev-lab"))
    import demo
    from players import JEV_MODES

    options = demo.parse_args(demo_args)
    modes = demo.parse_modes(options.mode)
    needs_jev = any(mode in JEV_MODES for mode in modes)
    if not options.cdp:
        ensure_browser()
    if needs_jev:
        ensure_jev(override)
        from jev_client import load_model_module
        load_model_module()
    if args.setup_only:
        say("Setup complete. Run python3 start.py to play; no API request was made.")
        return 0
    if needs_jev:
        configure_key()
    say("Starting demo. Ctrl-C to stop; --retro also stops when the game window closes.")
    from playwright.sync_api import Error
    try:
        return demo.main(demo_args)
    except Error as exc:
        raise RuntimeError("Browser session failed. Check the Chromium installation and, "
                           "when using --retro, desktop availability.\n%s" % exc) from exc


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        raise SystemExit(0)
    except (OSError, RuntimeError, ValueError, ImportError, zipfile.BadZipFile, EOFError) as exc:
        print("[setup] Cannot start: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
