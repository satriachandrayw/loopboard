import re
from pathlib import Path

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


def api_operations() -> list[str]:
    """Every `METHOD /path` under /api, from the OpenAPI schema (it sees routes in mounted routers too)."""
    paths = build_app().openapi()["paths"]
    return [f"{m.upper()} {p}" for p, ops in paths.items() if p.startswith("/api")
            for m in ops if m.upper() not in ("HEAD", "OPTIONS")]


def test_api_doc_sees_every_api_route():
    ops = api_operations()
    assert len(ops) >= 20, ops
    assert "GET /api/board" in ops and "POST /api/items/{item_id}/link" in ops


def test_api_doc_lists_every_route():
    text = DOC.read_text()
    missing = [op for op in api_operations() if not documented(text, *op.split(" ", 1))]
    assert not missing, missing
