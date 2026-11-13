from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import __version__
from .contract import IngestRejected, SourceError

CHUNK = 100
COUNTS = ("accepted", "created", "updated", "skipped_older", "unknown_epic", "linked_task", "auto_tasks",
          "unknown_task")
# A real User-Agent: Cloudflare's Browser Integrity Check rejects the default Python-urllib one (error 1010).
USER_AGENT = f"loopboard-connectors/{__version__} (+https://github.com/satriachandrayw/loopboard)"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None  # a redirect surfaces as HTTPError; the token is never forwarded


_OPENER = urllib.request.build_opener(_NoRedirect)


def _urllib_post(url: str, body: bytes, headers: dict) -> dict:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with _OPENER.open(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise IngestRejected(e.code, e.reason if isinstance(e.reason, str) else "") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise IngestRejected(0, "request failed") from None


class IngestClient:
    def __init__(self, base_url: str, token: str, *, post=None):
        self.url = base_url.rstrip("/") + "/api/ingest"
        self._token = token
        self._post = post or _urllib_post
        self.posts = 0

    def send(self, source: str, items) -> dict:
        totals = {k: 0 for k in COUNTS}
        items = list(items)
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json",
                   "User-Agent": USER_AGENT}
        for i in range(0, len(items), CHUNK):
            body = json.dumps({"source": source, "items": [it.to_payload() for it in items[i:i + CHUNK]]}).encode()
            res = self._post(self.url, body, headers)
            self.posts += 1
            for k in COUNTS:
                totals[k] += int(res.get(k, 0))
        return totals
