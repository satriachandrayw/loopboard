"""Connector contract: read-only sources producing Items for POST /api/ingest."""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

ABILITIES = ("read",)

# v1a.4: a title starting with "[DEMO-E5] " names the epic the item belongs to; tasks design:
# "[DEMO-12] " names the task. Only the leading position counts.
KEY_PREFIX = re.compile(r"^\s*\[([A-Z][A-Z0-9]{1,9}-(?:E[0-9]+|[0-9]+))\]\s*(.+)$")


def split_key_prefix(title: str) -> tuple[str | None, str | None, str]:
    """Return (epic_key, task_key, title without the prefix); (None, None, title) when the title does
    not start with a well-formed [EPIC-KEY] or [TASK-KEY]."""
    m = KEY_PREFIX.match(title)
    if not m:
        return None, None, title
    key, rest = m.group(1), m.group(2)
    return (key, None, rest) if "-E" in key else (None, key, rest)


def split_epic_prefix(title: str) -> tuple[str | None, str]:
    """Epic prefix only: (epic_key, rest), or (None, title) for anything else (a task prefix too)."""
    epic, _, rest = split_key_prefix(title)
    return (epic, rest) if epic else (None, title)


class SourceError(RuntimeError):
    """The source could not be read or returned unusable data."""


class ConfigError(RuntimeError):
    """Configuration or token is missing or invalid."""


class IngestRejected(RuntimeError):
    def __init__(self, status: int, message: str = ""):
        super().__init__(f"ingest rejected ({status}): {message}" if message else f"ingest rejected ({status})")
        self.status = status


@dataclass
class Item:
    source: str
    external_id: str
    title: str
    url: str | None
    status_category: str
    raw_status: str
    owner: str | None
    waiting_on: str | None
    blocked_reason: str | None
    next_step: str | None
    project_key: str | None
    epic_key: str | None
    last_activity_at: str
    merged_at: str | None = None
    live_at: str | None = None
    task_key: str | None = None

    def to_payload(self) -> dict:
        d = asdict(self)
        d.pop("source")
        for k in ("epic_key", "task_key"):
            if d[k] is None:
                del d[k]
        return d
