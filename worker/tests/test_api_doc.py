import re
from pathlib import Path

from fastapi.routing import APIRoute

from loopboard.app import build_app

DOC = Path(__file__).resolve().parents[2] / "docs" / "api.md"


def documented(text: str, method: str, path: str) -> bool:
    """`METHOD /path` must be a whole line (optionally a markdown heading)."""
    pat = rf"^(?:#+\s+)?{re.escape(method)}\s+{re.escape(path)}\s*$"
    return re.search(pat, text, re.MULTILINE) is not None


def test_documented_matches_whole_line_only():
    text = "### GET /api/epics/{key}/x\nsee GET /api/foo here\n## POST /api/bar\n"
    assert not documented(text, "GET", "/api/epics/{key}")
    assert not documented(text, "GET", "/api/foo")
    assert documented(text, "POST", "/api/bar")


def test_api_doc_lists_every_route():
    text = DOC.read_text()
    missing = []
    for r in build_app().routes:
        if isinstance(r, APIRoute) and r.path.startswith("/api"):
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                if not documented(text, m, r.path):
                    missing.append(f"{m} {r.path}")
    assert not missing, missing
