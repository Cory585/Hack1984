"""Tiny stdlib web server.

    python -m conflict_check.server [--replay] [--port 8000] [--cache-dir demo-cache]

Routes
  GET  /                 the UI
  GET  /api/config       replay default, which keys are set (stale-while-revalidate)
  GET  /api/demo         the fictional demo article
  POST /api/experts      step 1: {url|text, demo?} -> article text + extracted experts to review
  POST /api/check        step 2: {url|text, experts?, replay?, demo?} -> full JSON result
  POST /api/check/stream same, as NDJSON events: call, start, expert, done | error
"demo": true runs the real pipeline on fictional data (conflict_check/demo.py): no keys, no network.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .demo import ARTICLE as DEMO_ARTICLE, demo_session
from .openpayments import datasets as op_datasets
from .pipeline import check_article, find_experts
from .session import Session

MAX_BODY = 2_000_000  # 2 MB is plenty for an article plus an expert list


class BadRequest(Exception):
    """A request we refuse before doing any work; carries its HTTP status (400 or 413)."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web", "index.html")
CACHE = os.path.join(ROOT, "cache")


def load_env(path: str = os.path.join(ROOT, ".env")) -> None:
    # CC_NO_DOTENV=1 ignores .env (the e2e walk uses it to run a server with no API keys).
    if os.environ.get("CC_NO_DOTENV") or not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cache_dir() -> str:
    d = os.environ.get("CACHE_DIR") or CACHE
    return d if os.path.isabs(d) else os.path.join(ROOT, d)


class Handler(BaseHTTPRequestHandler):
    default_replay = False
    quiet = False  # tests turn request logging off

    def log_message(self, fmt, *args):  # quieter console
        if not self.quiet and "/api/" in (self.path or ""):
            super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes, ctype: str, cache: str = "no-store") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj, cache: str = "no-store") -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json", cache)

    def _body(self) -> dict:
        """Read the JSON body. Never trusts Content-Length blindly: a negative or non-numeric length
        is rejected before reading (rfile.read(-1) would block the thread), and an oversize body is
        refused with 413 without reading it. Both close the connection so no unread bytes linger."""
        raw = (self.headers.get("Content-Length") or "0").strip()
        if not raw.isdigit():
            self.close_connection = True
            raise BadRequest(400, "invalid Content-Length")
        n = int(raw)
        if n > MAX_BODY:
            self.close_connection = True
            raise BadRequest(413, f"request too large (limit {MAX_BODY // 1_000_000} MB)")
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise BadRequest(400, "invalid JSON")

    def _session(self, req: dict, **kw) -> Session:
        if req.get("demo"):
            return demo_session(on_call=kw.get("on_call"))
        return Session(cache_dir=cache_dir(), replay=bool(req.get("replay", self.default_replay)), **kw)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            with open(WEB, "rb") as f:
                # Always revalidate the page so a demo laptop never shows a stale UI.
                self._send(200, f.read(), "text/html; charset=utf-8", "no-cache")
        elif path == "/api/config":
            # Rarely changes: serve from cache instantly, refresh in the background.
            self._json(200, {"replay_default": self.default_replay, "cache_dir": os.path.relpath(cache_dir(), ROOT),
                             "keys": {"tavily": bool(os.environ.get("TAVILY_API_KEY")),
                                      "exa": bool(os.environ.get("EXA_API_KEY"))},
                             # the page's Open Payments copy follows OPEN_PAYMENTS / OPEN_PAYMENTS_DATASETS
                             "open_payments": {"enabled": bool(op_datasets()), "years": sorted(op_datasets())}},
                       "max-age=0, stale-while-revalidate=300")
        elif path == "/api/demo":
            self._json(200, {"text": DEMO_ARTICLE}, "max-age=3600")
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        try:
            req = self._body()
        except BadRequest as e:
            return self._json(e.code, {"error": str(e)})
        if not isinstance(req, dict):
            return self._json(400, {"error": "expected a JSON object"})
        if self.path == "/api/check/stream":
            return self._stream(req)
        try:
            if self.path == "/api/experts":
                s = self._session(req)
                self._json(200, find_experts(s, url=req.get("url") or None, text=req.get("text") or None))
            elif self.path == "/api/check":
                s = self._session(req)
                self._json(200, check_article(s, url=req.get("url") or None, text=req.get("text") or None,
                                              experts=req.get("experts")))
            else:
                self._json(404, {"error": "not found"})
        except ValueError as e:
            self._json(400, {"error": str(e)})
        except Exception as e:
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def _stream(self, req: dict) -> None:
        """Run the check on a worker thread; forward each API call and expert result as one JSON line."""
        events: queue.Queue = queue.Queue()
        s = self._session(req, on_call=lambda c: events.put({"type": "call", "call": c}))

        def work():
            try:
                result = check_article(s, url=req.get("url") or None, text=req.get("text") or None,
                                       experts=req.get("experts"), on_event=events.put)
                result.pop("calls", None)  # already streamed
                events.put({"type": "done", "result": result})
            except Exception as e:
                events.put({"type": "error", "error": str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"})
            events.put(None)

        threading.Thread(target=work, daemon=True).start()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()  # HTTP/1.0: the connection closes when the stream ends
        while (ev := events.get()) is not None:
            try:
                self.wfile.write((json.dumps(ev) + "\n").encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--replay", action="store_true", help="serve cached responses only (demo mode)")
    ap.add_argument("--cache-dir", help="response cache folder (default: cache/, or CACHE_DIR)")
    args = ap.parse_args()
    load_env()
    if args.cache_dir:
        os.environ["CACHE_DIR"] = args.cache_dir
    Handler.default_replay = args.replay
    print(f"Conflict Check on http://localhost:{args.port}  "
          f"(replay={'on' if args.replay else 'off'}, cache={os.path.relpath(cache_dir(), ROOT)})")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
