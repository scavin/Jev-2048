"""Dashboard commands must not stop a demo launched without a dashboard."""

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "jev-lab"))

from runner.interactive import InteractiveHook


class DashboardIsolationTest(unittest.IsolatedAsyncioTestCase):
    async def test_retro_ignores_saved_pause_and_step_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            control_path = Path(directory) / "control.json"
            control_path.write_text(json.dumps({
                "seq": 2, "command": "pause", "pending_steps": 1, "speed": "1",
            }))
            hook = InteractiveHook(
                None, "random", 2048, speed="5", panel=False, echo=False,
                control_path=str(control_path),
            )
            # A stale pending step used to allow one move, then block forever.
            for _ in range(2):
                live = {}
                await asyncio.wait_for(hook.before_step(live), timeout=1)
                self.assertEqual(live["status"], "deciding")
                self.assertFalse(live["paused"])
                self.assertEqual(live["speed"], "5")


if __name__ == "__main__":
    unittest.main()
