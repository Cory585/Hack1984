"""API session: disk cache keyed by request, replay mode, and a visible call log.

Every outbound call goes through Session.request so that:
  * nothing is fetched twice (saves Tavily/Exa credits),
  * replay mode can serve the demo with no network,
  * the UI can show every Tavily / Exa / ORCID call (the "API panel").
API keys are never written to the cache.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

Fetcher = Callable[[str, str, dict, Any], Any]


class ReplayMiss(Exception):
    """Raised in replay mode when a request has no cached response."""


class MissingKey(Exception):
    pass


def urllib_fetcher(method: str, url: str, headers: dict, body: Any) -> Any:
    data = None
    headers = {"User-Agent": "conflict-check/0.1", "Accept": "application/json", **headers}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {e.code} from {url}: {detail}") from e


class Session:
    def __init__(
        self,
        cache_dir: str | None = "cache",
        replay: bool = False,
        fetcher: Fetcher | None = None,
        tavily_key: str | None = None,
        exa_key: str | None = None,
        on_call: Callable[[dict], None] | None = None,
    ):
        self.cache_dir = cache_dir
        self.replay = replay
        self.fetcher = fetcher or urllib_fetcher
        self.tavily_key = tavily_key if tavily_key is not None else os.environ.get("TAVILY_API_KEY")
        self.exa_key = exa_key if exa_key is not None else os.environ.get("EXA_API_KEY")
        self.calls: list[dict] = []
        self.on_call = on_call  # e.g. stream each call to the UI's API panel as it happens

    def key(self, api: str) -> str:
        k = {"tavily": self.tavily_key, "exa": self.exa_key}.get(api)
        if not k and not self.replay:
            raise MissingKey(f"{api.upper()}_API_KEY is not set (or use replay mode)")
        return k or ""

    def request(self, api: str, label: str, method: str, url: str,
                headers: dict | None = None, body: Any = None) -> Any:
        key_src = json.dumps({"m": method, "u": url, "b": body}, sort_keys=True)
        digest = hashlib.sha256(key_src.encode("utf-8")).hexdigest()[:32]
        # cache_dir=None: no disk cache at all (the built-in demo), so nothing is left behind.
        path = os.path.join(self.cache_dir, api, digest + ".json") if self.cache_dir else None
        t0 = time.perf_counter()

        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)["response"]
            self._log(api, label, "cache", t0)
            return data
        if self.replay:
            self._log(api, label, "miss", t0, "not cached (replay mode)")
            raise ReplayMiss(f"Not cached (replay mode); run once live first. Missing: {label}")
        try:
            data = self.fetcher(method, url, headers or {}, body)
        except Exception as e:
            self._log(api, label, "error", t0, str(e)[:200])
            raise
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = f"{path}.{os.getpid()}.tmp"  # write then rename: concurrent requests never see half a file
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"request": {"method": method, "url": url, "body": body}, "response": data}, f)
            os.replace(tmp, path)
        self._log(api, label, "live", t0)
        return data

    def _log(self, api: str, label: str, source: str, t0: float, error: str | None = None) -> None:
        call = {
            "n": len(self.calls) + 1,
            "api": api,
            "label": label,
            "source": source,  # live | cache | miss | error
            "ms": round((time.perf_counter() - t0) * 1000),
            "error": error,
        }
        self.calls.append(call)
        if self.on_call:
            self.on_call(call)
