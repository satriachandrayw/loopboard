"""Stall rules (D10)."""
from .derive import Derived, TaskDerived, effective_category, live_links, open_items
from .model import OPEN_CATEGORIES, STALL_DEFAULT_HOURS


def threshold_hours(thresholds: dict[str, float], source: str) -> float:
    return float(thresholds.get(source, STALL_DEFAULT_HOURS))


def item_stalled(item: dict, now: int, thresholds: dict[str, float]) -> bool:
    if item.get("filing") == "ignored" or effective_category(item) not in OPEN_CATEGORIES:
        return False
    return now - item["last_activity_at"] > threshold_hours(thresholds, item["source"]) * 3600


def epic_stalled(epic: dict, items: list[dict], derived: Derived, now: int,
                 thresholds: dict[str, float]) -> bool:
    if derived.board_column not in ("todo", "in_progress", "review"):
        return False
    op = open_items(items)
    if op:
        limit = min(threshold_hours(thresholds, i["source"]) for i in op)
        newest = max(i["last_activity_at"] for i in op)
        return now - newest > limit * 3600
    return now - epic["last_activity_at"] > STALL_DEFAULT_HOURS * 3600


def task_stalled(task: dict, items: list[dict], derived: TaskDerived, now: int,
                 thresholds: dict[str, float]) -> bool:
    """Open and nothing moved (the task or a live link) for longer than the smallest threshold
    among its links' sources, or the 24 h default without links."""
    if derived.status not in ("todo", "in_progress", "review"):
        return False
    links = live_links(items)
    limit = min((threshold_hours(thresholds, i["source"]) for i in links), default=STALL_DEFAULT_HOURS)
    newest = max([task["last_activity_at"]] + [i["last_activity_at"] for i in links])
    return now - newest > limit * 3600
