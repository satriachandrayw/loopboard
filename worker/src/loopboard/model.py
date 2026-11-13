"""Shared constants and timestamp parsing."""
import re
from datetime import datetime, timezone

CATEGORIES = ("backlog", "todo", "in_progress", "blocked", "review", "done", "canceled")
OPEN_CATEGORIES = ("backlog", "todo", "in_progress", "blocked", "review")
FILINGS = ("unfiled", "epic", "standalone", "ignored")
EPIC_MANUAL_COLUMNS = ("backlog", "todo", "canceled")
STAGES = ("idea", "spec", "plan", "build", "review", "ship")
DAY = 86400
DONE_HIDE_SECONDS = 7 * DAY
REVIEW_WARN_AT = 3
STALL_DEFAULT_HOURS = 24.0
TASK_TYPES = ("task", "bug")
TASK_STATUSES = ("todo", "in_progress", "review", "done", "canceled")
PRIORITIES = ("high", "medium", "low")
TASK_KEY = r"^[A-Z][A-Z0-9]{1,9}-[0-9]+$"
EPIC_KEY = r"^[A-Z][A-Z0-9]{1,9}-E[0-9]+$"


class ValidationError(ValueError):
    pass


def parse_ts(value: str) -> int:
    """ISO 8601 with explicit offset or Z -> epoch seconds UTC (D16)."""
    try:
        s = value.strip()
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, AttributeError) as e:
        raise ValidationError(f"invalid timestamp: {value!r}") from e
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValidationError("timestamp needs an explicit offset or Z")
    try:
        return int(dt.astimezone(timezone.utc).timestamp())
    except (OverflowError, OSError, ValueError) as e:
        raise ValidationError(f"timestamp out of range: {value!r}") from e


# --- ingest payload models (pydantic) ---
from typing import Literal  # noqa: E402

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator  # noqa: E402


def _http_url(v):
    if v is not None and not v.startswith(("http://", "https://")):
        raise ValueError("url must start with http:// or https://")
    return v


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    url: str | None = Field(default=None, max_length=500)
    status_category: Literal[CATEGORIES]  # type: ignore[valid-type]
    raw_status: str | None = Field(default=None, max_length=100)
    owner: str | None = Field(default=None, max_length=100)
    waiting_on: str | None = Field(default=None, pattern=r"^(agent|human|source):[A-Za-z0-9._-]{1,64}$")
    blocked_reason: Literal["needs_input", "other"] | None = None
    next_step: str | None = Field(default=None, max_length=200)
    project_key: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9]{1,9}$")
    epic_key: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9]{1,9}-E[0-9]+$")
    task_key: str | None = Field(default=None, pattern=TASK_KEY)
    last_activity_at: str
    merged_at: str | None = None
    live_at: str | None = None

    _url = field_validator("url")(_http_url)

    @field_validator("last_activity_at", "merged_at", "live_at")
    @classmethod
    def _ts(cls, v):
        if v is not None:
            parse_ts(v)
        return v

    @model_validator(mode="after")
    def _waiting(self):
        if self.status_category in OPEN_CATEGORIES and not self.waiting_on:
            raise ValidationError("waiting_on is required on open items")
        return self


class IngestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    items: list[ItemIn] = Field(max_length=100)


# --- write API models ---
_WAITING = r"^(agent|human|source):[A-Za-z0-9._-]{1,64}$"


def _description(v):
    """Epic goal (shown as "Description"): stripped, never blank. None passes through for PATCH, where
    writes.NOT_NULL rejects an explicit null; EpicIn's `str` type already refuses None."""
    if v is None:
        return v
    v = v.strip()
    if not v:
        raise ValueError("goal cannot be blank")
    return v


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,9}$")
    name: str = Field(min_length=1, max_length=100)


class EpicIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(max_length=2000)
    stage: Literal[STAGES] = "idea"  # type: ignore[valid-type]
    owner: str | None = Field(default=None, max_length=100)
    next_step: str | None = Field(default=None, max_length=200)
    waiting_on: str | None = Field(default=None, pattern=_WAITING)
    home_url: str | None = Field(default=None, max_length=500)
    spec_url: str | None = Field(default=None, max_length=500)
    plan_url: str | None = Field(default=None, max_length=500)
    manual_column: Literal[EPIC_MANUAL_COLUMNS] = "backlog"  # type: ignore[valid-type]

    _urls = field_validator("home_url", "spec_url", "plan_url")(_http_url)
    _goal = field_validator("goal")(_description)

    @model_validator(mode="after")
    def _waiting(self):
        if self.manual_column != "canceled" and not self.waiting_on:
            raise ValidationError("waiting_on is required unless the epic is canceled")
        return self


class EpicPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    goal: str | None = Field(default=None, max_length=2000)
    stage: Literal[STAGES] | None = None  # type: ignore[valid-type]
    owner: str | None = Field(default=None, max_length=100)
    next_step: str | None = Field(default=None, max_length=200)
    waiting_on: str | None = Field(default=None, pattern=_WAITING)
    home_url: str | None = Field(default=None, max_length=500)
    spec_url: str | None = Field(default=None, max_length=500)
    plan_url: str | None = Field(default=None, max_length=500)
    manual_column: Literal[EPIC_MANUAL_COLUMNS] | None = None  # type: ignore[valid-type]

    _urls = field_validator("home_url", "spec_url", "plan_url")(_http_url)
    _goal = field_validator("goal")(_description)


class FilingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filing: Literal["epic", "standalone", "ignored"]
    epic_key: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9]{1,9}-E[0-9]+$")
    project_key: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9]{1,9}$")


_Refs = list[str]


def _refs(v):
    if v is None:
        return v
    out = []
    for r in v:
        r = r.strip() if isinstance(r, str) else r
        if not isinstance(r, str) or not re.fullmatch(TASK_KEY, r):
            raise ValueError("refs look like ABC-123")
        if r not in out:
            out.append(r)
    return out


class TaskIn(BaseModel):
    """A new task. Strings are stripped first, so a blank field fails its min_length (422)."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=2000)
    done_when: str = Field(min_length=1, max_length=300)
    owner: str = Field(min_length=1, max_length=100)
    waiting_on: str = Field(pattern=_WAITING)
    type: Literal[TASK_TYPES] = "task"  # type: ignore[valid-type]
    priority: Literal[PRIORITIES] = "medium"  # type: ignore[valid-type]
    epic_key: str | None = Field(default=None, pattern=EPIC_KEY)
    refs: _Refs = Field(default_factory=list, max_length=10)
    item_id: int | None = None

    _refs = field_validator("refs")(_refs)


class TaskPatch(BaseModel):
    """Every field optional; `epic_key: null` moves the task to No epic. Explicit nulls on the
    required text fields are refused in writes.patch_task."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    done_when: str | None = Field(default=None, min_length=1, max_length=300)
    owner: str | None = Field(default=None, min_length=1, max_length=100)
    waiting_on: str | None = Field(default=None, pattern=_WAITING)
    type: Literal[TASK_TYPES] | None = None  # type: ignore[valid-type]
    priority: Literal[PRIORITIES] | None = None  # type: ignore[valid-type]
    epic_key: str | None = Field(default=None, pattern=EPIC_KEY)
    refs: _Refs | None = Field(default=None, max_length=10)

    _refs = field_validator("refs")(_refs)


class TaskStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[TASK_STATUSES]  # type: ignore[valid-type]


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_key: str = Field(pattern=TASK_KEY)


class MergeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    into: str = Field(pattern=TASK_KEY)


class DeployedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    live_at: str

    @field_validator("live_at")
    @classmethod
    def _ts(cls, v):
        parse_ts(v)
        return v


class RelationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_type: Literal["epic", "item"]
    from_id: int
    to_type: Literal["epic", "item"]
    to_id: int


class SourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stall_hours: float = Field(gt=0, le=8760)
