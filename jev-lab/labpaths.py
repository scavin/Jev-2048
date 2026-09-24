"""Import paths and constants shared by every module in the lab.

The lab reuses two things that already exist on disk rather than copying them:

* `game-test/game_client.py` — the black-box page client (DOM + localStorage only) and
  `game-test/reference2048.py` — an independent rules engine, which the lab uses as its
  simulator and as ground truth for "was this move legal".
* `browser-use/jev-ultrafast` — jev's own HTTP client (`model.post_json`,
  `model.validate_choice`), so every decision goes over the shipped network path.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

GAME_TEST_DIR = os.path.join(REPO, "game-test")
# Holds the loader that imports jev's own `model.py` without the browser agent around it.
JEV_TEST_DIR = os.path.join(REPO, "jev-test")
JEV_REPO = os.environ.get("JEV_REPO", "/Users/scavin/Documents/Github/Jev")

for _path in (HERE, GAME_TEST_DIR, JEV_TEST_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

GAME_URL = os.environ.get("GAME_URL", "http://127.0.0.1:8792/index.html")
LOGS_DIR = os.path.join(HERE, "logs")
RESULTS_DIR = os.path.join(HERE, "results")
UI_DIR = os.path.join(HERE, "ui")

for _dir in (LOGS_DIR, RESULTS_DIR):
    os.makedirs(_dir, exist_ok=True)
