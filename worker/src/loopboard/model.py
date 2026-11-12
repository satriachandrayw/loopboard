"""Shared constants and timestamp parsing."""
from datetime import datetime

CATEGORIES = ("backlog", "todo", "in_progress", "blocked", "review", "done", "canceled")
OPEN_CATEGORIES = ("backlog", "todo", "in_progress", "blocked", "review")
FILINGS = ("unfiled", "epic", "standalone", "ignored")
EPIC_MANUAL_COLUMNS = ("backlog", "todo", "canceled")
STAGES = ("idea", "spec", "plan", "build", "review", "ship")
DAY = 86400
DONE_HIDE_SECONDS = 7 * DAY
REVIEW_WARN_AT = 3
STALL_DEFAULT_HOURS = 24.0


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
    return int(dt.timestamp())
