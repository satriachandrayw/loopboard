"""Asks file connector (read-only): one JSON file of decisions an agent is waiting on the human for,
written by the owner's assistant. Each ask becomes an Item carrying its own question and reply code;
the Worker gives a new open one its own task on Needs you. Answering stays in chat.

File shape: {"asks": [{"code", "question", "project", "status", "updated_at", "url"?}]}. Any bad field
fails the whole run, so nothing is posted.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from .contract import Item, SourceError

STATUSES = ("open", "answered", "resolved", "expired", "dropped")
ANSWER_HOW = "Reply to your agent in chat with the code and your answer."
TEXT_MAX = 300
CODE_MAX = 40
URL_MAX = 500
_STRIP = re.compile(r"[\s_-]+")


def normalise(name: str) -> str:
    """Project name match key: lowercase, without spaces, '-' and '_' ("Cek Mitra" = "cekmitra")."""
    return _STRIP.sub("", name).lower()


def _iso(epoch) -> str:
    return datetime.fromtimestamp(int(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _field(ask: dict, key: str):
    if key not in ask:
        raise SourceError(f"ask is missing field: {key}")
    return ask[key]


def _text(ask: dict, key: str) -> str:
    v = _field(ask, key)
    if not isinstance(v, str) or not v.strip():
        raise SourceError(f"ask field {key} must be a non-empty string")
    return v.strip()


def map_ask(ask, *, source: str, human: str, projects: dict[str, str], default_project: str) -> Item:
    if not isinstance(ask, dict):
        raise SourceError("ask must be an object")
    code = _text(ask, "code")
    if len(code) > CODE_MAX:
        raise SourceError(f"ask code longer than {CODE_MAX} characters")
    question = _text(ask, "question")[:TEXT_MAX]
    project = _field(ask, "project")
    if project is not None and not isinstance(project, str):
        raise SourceError(f"ask {code}: project must be a string")
    status = _field(ask, "status")
    if status not in STATUSES:
        raise SourceError(f"ask {code}: unknown status")
    updated = _field(ask, "updated_at")
    if isinstance(updated, bool) or not isinstance(updated, (int, float)) or not math.isfinite(updated) \
            or updated < 0:
        raise SourceError(f"ask {code}: updated_at must be epoch seconds")
    url = ask.get("url")
    if url is not None and (not isinstance(url, str) or len(url) > URL_MAX
                            or not url.startswith(("http://", "https://"))):
        raise SourceError(f"ask {code}: url must be http(s)")
    names = {normalise(k): v for k, v in projects.items()}
    key = names.get(normalise(project or "")) or default_project
    is_open = status == "open"
    return Item(
        source=source, external_id=code, title=question, url=url,
        status_category="todo" if is_open else "done", raw_status=status, owner=None,
        waiting_on=f"human:{human}" if is_open else None, blocked_reason=None, next_step=None,
        project_key=key, epic_key=None, last_activity_at=_iso(updated),
        question=question, answer_how=ANSWER_HOW, reply_code=code,
    )


def load(path) -> list:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError:
        raise SourceError("cannot read asks file") from None
    except ValueError:
        raise SourceError("unparseable asks file") from None
    if not isinstance(data, dict) or not isinstance(data.get("asks"), list):
        raise SourceError('asks file must be {"asks": [...]}')
    return data["asks"]


def collect(path, *, source: str, human: str, projects: dict[str, str], default_project: str) -> list[Item]:
    return [map_ask(a, source=source, human=human, projects=projects, default_project=default_project)
            for a in load(path)]
