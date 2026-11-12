"""Connector contract: read-only sources producing Items for POST /api/ingest."""
from __future__ import annotations

from dataclasses import dataclass, asdict

ABILITIES = ("read",)


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

    def to_payload(self) -> dict:
        d = asdict(self)
        d.pop("source")
        if d["epic_key"] is None:
            del d["epic_key"]
        return d
