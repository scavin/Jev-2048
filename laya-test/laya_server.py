#!/usr/bin/env python3
"""Persistent Laya decision server.

Loading the checkpoint costs ~24s (ModernBERT-large encoder on MPS). A test loop
cannot pay that per question, so this process loads the agent once and answers
newline-delimited JSON requests over a local TCP socket.

Protocol (one JSON object per line, both directions):
  request : {"id": <any>, "state": <str|dict|list>, "questions": {...}}
  response: {"id": <same>, "ok": true,  "result": <laya response>}
            {"id": <same>, "ok": false, "error": "<repr>"}

Run:  <venv>/bin/python laya_server.py [--port 8791] [--device mps]
"""

import argparse
import json
import os
import socketserver
import sys
import traceback

# Must precede laya/transformers imports; see the upstream model card.
os.environ.setdefault("USE_TF", "0")

import laya  # noqa: E402

DEFAULT_MODEL = "convaiinnovations/laya"
DEFAULT_SUBFOLDER = "typed-decisions"

_AGENT = None


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        for raw in self.rfile:
            raw = raw.strip()
            if not raw:
                continue
            try:
                request = json.loads(raw)
            except ValueError as exc:
                self._write({"id": None, "ok": False, "error": "bad json: %s" % exc})
                continue

            if request.get("op") == "quit":
                self._write({"id": request.get("id"), "ok": True, "result": {"bye": True}})
                return

            if request.get("op") == "ping":
                self._write({"id": request.get("id"), "ok": True,
                             "result": {"device": str(_AGENT.device)}})
                continue

            try:
                result = _AGENT.predict(request["state"], request["questions"])
                self._write({"id": request.get("id"), "ok": True, "result": result})
            except Exception:
                self._write({"id": request.get("id"), "ok": False,
                             "error": traceback.format_exc(limit=3)})

    def _write(self, payload):
        self.wfile.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        self.wfile.flush()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    global _AGENT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--subfolder", default=DEFAULT_SUBFOLDER)
    parser.add_argument("--device", default="mps")
    args = parser.parse_args()

    _AGENT = laya.load(args.model, subfolder=args.subfolder, device=args.device)
    print("[laya-server] ready device=%s port=%d" % (_AGENT.device, args.port), flush=True)

    with Server((args.host, args.port), Handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
