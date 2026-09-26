"""The key store and the panel endpoint that fills it.

A key is the one secret this project handles, so the rules it must keep are asserted here
rather than assumed: it is written owner-only, outside the repository, never returned to a
browser, and never placed in a file the panel reads.
"""

import asyncio
import http.client
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "jev-lab"))

import credentials
from runner.interactive import await_api_key
from ui.dashboard import Dashboard

SAMPLE = "test-key-not-a-real-credential"


def post(url, payload, headers=None):
    """POST without inheriting a proxy from the environment: this is a loopback test."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url + "api/key", method="POST",
                                     data=json.dumps(payload).encode(),
                                     headers=dict({"Content-Type": "application/json"},
                                                  **(headers or {})))
    with opener.open(request, timeout=5) as response:
        return response.status, response.read().decode()


class KeyStoreTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_file = credentials.KEY_FILE
        self.original_env = os.environ.get(credentials.ENV_NAME)
        credentials.KEY_FILE = Path(self.directory.name) / "config" / "credentials.env"
        os.environ.pop(credentials.ENV_NAME, None)

    def tearDown(self):
        credentials.KEY_FILE = self.original_file
        os.environ.pop(credentials.ENV_NAME, None)
        if self.original_env is not None:
            os.environ[credentials.ENV_NAME] = self.original_env
        self.directory.cleanup()

    def test_save_is_owner_only_and_outside_any_repository(self):
        path = credentials.save(SAMPLE)
        self.assertEqual(path.read_text().strip(), "%s=%s" % (credentials.ENV_NAME, SAMPLE))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_status_separates_a_saved_key_from_a_session_one(self):
        self.assertEqual(credentials.status(), {"configured": False, "saved": False})
        os.environ[credentials.ENV_NAME] = SAMPLE
        self.assertEqual(credentials.status(), {"configured": True, "saved": False})
        credentials.save(SAMPLE)
        self.assertEqual(credentials.status(), {"configured": True, "saved": True})

    def test_a_saved_key_is_loaded_without_clobbering_the_environment(self):
        credentials.save("from-the-file")
        credentials.load()
        self.assertEqual(os.environ[credentials.ENV_NAME], "from-the-file")
        os.environ[credentials.ENV_NAME] = "from-the-environment"
        credentials.load()
        self.assertEqual(os.environ[credentials.ENV_NAME], "from-the-environment")

    def test_status_never_carries_the_key(self):
        credentials.save(SAMPLE)
        self.assertNotIn(SAMPLE, json.dumps(credentials.status()))


class KeyEndpointTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_file = credentials.KEY_FILE
        self.original_env = os.environ.get(credentials.ENV_NAME)
        credentials.KEY_FILE = Path(self.directory.name) / "config" / "credentials.env"
        os.environ.pop(credentials.ENV_NAME, None)
        root = Path(self.directory.name)
        self.board = Dashboard(port=0, state_path=str(root / "live_state.json"),
                               control_path=str(root / "control.json"),
                               screenshot_path=str(root / "live.jpg"))
        self.url = self.board.start()

    def tearDown(self):
        self.board.stop()
        credentials.KEY_FILE = self.original_file
        os.environ.pop(credentials.ENV_NAME, None)
        if self.original_env is not None:
            os.environ[credentials.ENV_NAME] = self.original_env
        self.directory.cleanup()

    def test_the_response_never_contains_the_key(self):
        status, body = post(self.url, {"key": SAMPLE, "save": False})
        self.assertEqual(status, 200)
        self.assertNotIn(SAMPLE, body)
        self.assertEqual(json.loads(body)["saved_to"], None)
        self.assertEqual(os.environ[credentials.ENV_NAME], SAMPLE)

    def test_saving_writes_the_file_and_reports_where(self):
        status, body = post(self.url, {"key": SAMPLE, "save": True})
        self.assertEqual(status, 200)
        self.assertNotIn(SAMPLE, body)
        self.assertEqual(json.loads(body)["saved_to"], str(credentials.KEY_FILE))
        self.assertEqual(stat.S_IMODE(credentials.KEY_FILE.stat().st_mode), 0o600)

    def test_a_bad_key_is_refused_without_touching_the_environment(self):
        for payload in ({"key": ""}, {"key": "   "}, {"key": "two\nlines"}, {"key": 7},
                        {"key": "x" * 513}, {}):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                post(self.url, payload)
            self.assertEqual(caught.exception.code, 400)
            caught.exception.read()   # drain it, so the server is not left mid-write
            caught.exception.close()
        self.assertIsNone(os.environ.get(credentials.ENV_NAME))
        self.assertFalse(credentials.KEY_FILE.exists())

    def test_a_request_to_another_host_name_is_refused(self):
        # The panel is unauthenticated and can write a credential, so a page that rebinds its
        # own domain to loopback must not be able to reach it.
        connection = http.client.HTTPConnection("127.0.0.1", self.board.port, timeout=5)
        try:
            connection.request("POST", "/api/key", json.dumps({"key": SAMPLE}),
                               {"Content-Type": "application/json", "Host": "rebind.example"})
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
        finally:
            connection.close()
        self.assertIsNone(os.environ.get(credentials.ENV_NAME))


class ApiKeyGateTest(unittest.IsolatedAsyncioTestCase):
    """The runner waits for a key when a panel can collect one, and says so when it cannot."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_file = credentials.KEY_FILE
        self.original_env = os.environ.get(credentials.ENV_NAME)
        credentials.KEY_FILE = Path(self.directory.name) / "config" / "credentials.env"
        os.environ.pop(credentials.ENV_NAME, None)
        self.state = str(Path(self.directory.name) / "live_state.json")

    def tearDown(self):
        credentials.KEY_FILE = self.original_file
        os.environ.pop(credentials.ENV_NAME, None)
        if self.original_env is not None:
            os.environ[credentials.ENV_NAME] = self.original_env
        self.directory.cleanup()

    async def test_a_configured_key_does_not_gate(self):
        os.environ[credentials.ENV_NAME] = SAMPLE
        await asyncio.wait_for(
            await_api_key(("jev-features",), self.state, dashboard=True), timeout=1)

    async def test_a_baseline_never_gates(self):
        await asyncio.wait_for(
            await_api_key(("random", "greedy"), self.state, dashboard=False), timeout=1)

    async def test_it_waits_and_tells_the_panel_why(self):
        waiting = asyncio.create_task(
            await_api_key(("jev-features",), self.state, dashboard=True))
        await asyncio.sleep(0.4)
        self.assertFalse(waiting.done())
        published = json.loads(Path(self.state).read_text())
        self.assertEqual(published["status"], "waiting for api key")
        self.assertEqual(published["api_key"], {"configured": False, "saved": False})
        os.environ[credentials.ENV_NAME] = SAMPLE
        await asyncio.wait_for(waiting, timeout=3)

    async def test_without_a_panel_it_refuses_instead_of_hanging(self):
        with self.assertRaises(RuntimeError) as caught:
            await asyncio.wait_for(
                await_api_key(("jev-features",), self.state, dashboard=False), timeout=2)
        self.assertIn("no dashboard", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
