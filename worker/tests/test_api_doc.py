from pathlib import Path

from fastapi.routing import APIRoute

from loopboard.app import build_app

DOC = Path(__file__).resolve().parents[2] / "docs" / "api.md"


def test_api_doc_lists_every_route():
    text = DOC.read_text()
    missing = []
    for r in build_app().routes:
        if isinstance(r, APIRoute) and r.path.startswith("/api"):
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                if f"{m} {r.path}" not in text:
                    missing.append(f"{m} {r.path}")
    assert not missing, missing
