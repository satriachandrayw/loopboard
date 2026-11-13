"""Stall rules (D10)."""
from .derive import Derived, TaskDerived, effective_category, live_links, open_items
from .model import OPEN_CATEGORIES, PLANNED_SOURCE, PLANNED_STALL_HOURS, STALL_DEFAULT_HOURS


def threshold_hours(thresholds: dict[str, float], source: str) -> float:
    return float(thresholds.get(source, STALL_DEFAULT_HOURS))


def item_stalled(item: dict, now: int, thresholds: dict[str, float]) -> bool:
    if item.get("filing") == "ignored" or effective_category(item) not in OPEN_CATEGORIES:
        return False
    return now - item["last_activity_at"] > threshold_hours(thresholds, item["source"]) * 3600


OPEN_TASK_STATUSES = ("todo", "in_progress", "review")


def epic_stalled(epic: dict, items: list[dict], tasks: list[dict], derived: Derived, now: int,
                 thresholds: dict[str, float]) -> bool:
    """Open items: the smallest threshold among their sources, over the newest of them. Else open
    tasks (load_tasks rows; planned work): the `planned` threshold over the newest of the epic and
    those tasks. Else 24 h over the epic's own activity."""
    if derived.board_column not in OPEN_TASK_STATUSES:
        return False
    op = open_items(items)
    if op:
        limit = min(threshold_hours(thresholds, i["source"]) for i in op)
        newest = max(i["last_activity_at"] for i in op)
        return now - newest > limit * 3600
    open_tasks = [t["task"] for t in tasks if t["derived"].status in OPEN_TASK_STATUSES]
    if open_tasks:
        limit = float(thresholds.get(PLANNED_SOURCE, PLANNED_STALL_HOURS))
        newest = max([epic["last_activity_at"]] + [t["last_activity_at"] for t in open_tasks])
        return now - newest > limit * 3600
    return now - epic["last_activity_at"] > STALL_DEFAULT_HOURS * 3600


def task_stalled(task: dict, items: list[dict], derived: TaskDerived, now: int,
                 thresholds: dict[str, float]) -> bool:
    """Open and nothing moved (the task or a live link) for longer than the smallest threshold
    among its links' sources, or the `planned` threshold (7 days by default) without links."""
    if derived.status not in OPEN_TASK_STATUSES:
        return False
    links = live_links(items)
    if links:
        limit = min(threshold_hours(thresholds, i["source"]) for i in links)
    else:
        limit = float(thresholds.get(PLANNED_SOURCE, PLANNED_STALL_HOURS))
    newest = max([task["last_activity_at"]] + [i["last_activity_at"] for i in links])
    return now - newest > limit * 3600
