"""Dashboard commands must not stop a demo launched without a dashboard, a human move must be
played exactly once and in the order it was pressed, and the panel's move sequence must never
restart once the runner has caught up."""

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "jev-lab"))

from runner.interactive import InteractiveHook, reset_control_file
from ui.dashboard import Dashboard


def write(path, payload):
    path.write_text(json.dumps(payload))


def post(url, payload):
    """POST without inheriting a proxy from the environment: this is a loopback test."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url + "api/control", method="POST",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
    with opener.open(request, timeout=5) as response:
        return json.loads(response.read())


class MoveSequenceTest(unittest.TestCase):
    """The panel's counter is what the runner compares against, so it may only grow."""

    def test_sequence_survives_the_queue_being_drained(self):
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory) / "control.json"
            state = Path(directory) / "live_state.json"
            board = Dashboard(port=0, state_path=str(state), control_path=str(control),
                              screenshot_path=str(Path(directory) / "live.jpg"))
            url = board.start()
            try:
                write(state, {"moves_done": 0})
                sequence = []
                for direction in ("up", "left", "down"):
                    response = post(url, {"direction": direction})
                    self.assertEqual(response["manual"], True)
                    sequence.append(response["moves"][-1]["seq"])
                    # The runner plays it and the panel prunes it, leaving the queue empty.
                    write(state, {"moves_done": sequence[-1]})
                self.assertEqual(sequence, sorted(set(sequence)),
                                 "the counter restarted, so a later press would be ignored")
            finally:
                board.stop()

    def test_rejected_bodies_do_not_touch_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory) / "control.json"
            state = Path(directory) / "live_state.json"
            board = Dashboard(port=0, state_path=str(state), control_path=str(control),
                              screenshot_path=str(Path(directory) / "live.jpg"))
            url = board.start()
            try:
                for body in ({"direction": "sideways"}, {"command": "teleport"}):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        post(url, body)
                    caught.exception.close()
                self.assertFalse(control.exists(), "a rejected request wrote the control file")
            finally:
                board.stop()


class SessionStartTest(unittest.IsolatedAsyncioTestCase):
    """A new run must not inherit the mode or the unplayed moves of the last one."""

    async def test_reset_forgets_the_mode_and_the_queued_move(self):
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory) / "control.json"
            write(control, {"seq": 34, "command": "run", "speed": "20", "manual": True,
                            "moves": [{"seq": 33, "direction": "up"}], "move_seq": 33})
            reset_control_file(str(control))
            after = json.loads(control.read_text())
            self.assertFalse(after["manual"])
            self.assertEqual(after["moves"], [])
            hook = InteractiveHook(None, "random", 2048, panel=True, echo=False,
                                   control_path=str(control),
                                   state_path=str(Path(directory) / "state.json"))
            self.assertIsNone(await asyncio.wait_for(hook.choose(None), timeout=1))

    async def test_reset_records_the_speed_this_session_starts_with(self):
        # The file must agree with the flag, so the stale value is replaced rather than kept.
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory) / "control.json"
            write(control, {"seq": 34, "command": "run", "speed": "20"})
            reset_control_file(str(control), "1")
            self.assertEqual(json.loads(control.read_text())["speed"], "1")
            reset_control_file(str(control), "nonsense")
            self.assertEqual(json.loads(control.read_text())["speed"], "5")


class DashboardIsolationTest(unittest.IsolatedAsyncioTestCase):
    async def test_retro_ignores_saved_pause_and_step_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            control_path = Path(directory) / "control.json"
            write(control_path, {"seq": 2, "command": "pause", "pending_steps": 1, "speed": "1"})
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

    async def test_retro_ignores_queued_human_moves(self):
        with tempfile.TemporaryDirectory() as directory:
            control_path = Path(directory) / "control.json"
            write(control_path, {"seq": 1, "command": "run", "manual": True,
                                 "moves": [{"seq": 1, "direction": "up"}]})
            hook = InteractiveHook(None, "random", 2048, panel=False, echo=False,
                                   control_path=str(control_path))
            self.assertIsNone(await hook.choose(None))


class HumanTakeoverTest(unittest.IsolatedAsyncioTestCase):
    def build(self, directory, **control):
        control_path = Path(directory) / "control.json"
        write(control_path, dict({"seq": 1, "command": "run"}, **control))
        hook = InteractiveHook(
            None, "random", 2048, panel=True, echo=False, shots=False,
            control_path=str(control_path), state_path=str(Path(directory) / "state.json"),
        )
        return hook, control_path

    async def test_queued_moves_are_played_in_order_and_only_once(self):
        with tempfile.TemporaryDirectory() as directory:
            hook, _ = self.build(directory, manual=True, moves=[
                {"seq": 2, "direction": "left"},
                {"seq": 1, "direction": "up"},
            ])
            self.assertEqual((await hook.choose(None)).name, "up")
            self.assertEqual((await hook.choose(None)).name, "left")
            self.assertEqual(hook.control["moves_done"], 2)

    async def test_played_moves_are_not_replayed_after_a_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            hook, control_path = self.build(directory, manual=True,
                                            moves=[{"seq": 1, "direction": "down"}])
            self.assertEqual((await hook.choose(None)).name, "down")
            # A new game shares the control state, exactly as run_interactive passes it.
            restarted = InteractiveHook(
                None, "random", 2049, panel=True, echo=False, shots=False,
                control_path=str(control_path),
                state_path=str(Path(directory) / "state.json"), control=hook.control,
            )
            write(control_path, {"seq": 2, "command": "auto", "manual": False,
                                 "moves": [{"seq": 1, "direction": "down"}]})
            self.assertIsNone(await restarted.choose(None))

    async def test_handing_back_to_the_policy_releases_a_waiting_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            hook, control_path = self.build(directory, manual=True, moves=[])
            waiting = asyncio.create_task(hook.choose(None))
            await asyncio.sleep(0.3)
            self.assertFalse(waiting.done())
            write(control_path, {"seq": 2, "command": "auto", "manual": False, "moves": []})
            self.assertIsNone(await asyncio.wait_for(waiting, timeout=3))

    async def test_auto_mode_never_waits_for_a_human(self):
        with tempfile.TemporaryDirectory() as directory:
            hook, _ = self.build(directory, manual=False)
            self.assertIsNone(await asyncio.wait_for(hook.choose(None), timeout=1))


if __name__ == "__main__":
    unittest.main()
