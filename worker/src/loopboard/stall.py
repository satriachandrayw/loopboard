"""Stall rules (D10)."""
from .derive import Derived, effective_category, open_items
from .model import OPEN_CATEGORIES, STALL_DEFAULT_HOURS


def threshold_hours(thresholds: dict[str, float], source: str) -> float:
    return float(thresholds.get(source, STALL_DEFAULT_HOURS))


ITEMS_FOR_STALL = (
    "select i.*, e.manual_column as epic_manual_column, e.project_id as epic_project_id from items i "
    "left join epics e on e.id = i.epic_id where i.filing in ('epic', 'standalone')")


def stall_eligible(item: dict) -> bool:
    """Standalone items and items filed to an epic that is not canceled (D6, D13)."""
    if item.get("filing") == "standalone":
        return True
    return item.get("filing") == "epic" and item.get("epic_manual_column") != "canceled"


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
