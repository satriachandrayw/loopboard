"""Derived task status, epic column, flags and progress (D5-D8, tasks design)."""
from dataclasses import dataclass, field

from .model import DONE_HIDE_SECONDS, OPEN_CATEGORIES


def effective_category(item: dict) -> str:
    cat = item["status_category"]
    if cat == "review" and item.get("merged_at") and item.get("live_at"):
        return "done"
    return cat


@dataclass
class Derived:
    board_column: str
    flags: list[str] = field(default_factory=list)
    review_owner: str | None = None
    done: int = 0
    total: int = 0
    has_code: bool = False
    hidden: bool = False


def _human(w) -> bool:
    return bool(w) and w.startswith("human:")


REASONS = {
    "canceled": "Canceled",
    "manual": "Moved by hand",
    "awaiting_confirmation": "Done by an agent; waiting for a human to confirm",
    "in_progress": "In progress: a linked item is running",
    "merged_not_live": "Review: a linked PR is merged but not live yet",
    "review": "Review: a linked item is in review",
    "done": "Done: every linked item is done",
    "blocked": "In progress: a linked item is blocked",
    "todo": "Todo: linked items haven't started",
}


@dataclass
class TaskDerived:
    status: str
    flags: list[str]
    reason: str
    linked: bool
    links_done: int
    links_total: int
    waiting_on: str | None = None  # the task's own waiting_on, for the epic's review owner


def live_links(items: list[dict]) -> list[dict]:
    """Linked items that count: not ignored and not canceled at the source."""
    return [i for i in items if i.get("filing") != "ignored" and i["status_category"] != "canceled"]


def _merged_not_live(i: dict) -> bool:
    return bool(i.get("merged_at")) and not i.get("live_at")


def derive_task(task: dict, items: list[dict], merged_into_key: str | None = None) -> TaskDerived:
    """Displayed status of a task (spec "Lifecycle"): canceled wins; live links decide; else manual."""
    links = live_links(items)
    cats = [effective_category(i) for i in links]
    d = TaskDerived("todo", [], "", bool(links), sum(1 for c in cats if c == "done"), len(links),
                    task.get("waiting_on"))
    if task["status"] == "canceled":
        d.status = "canceled"
        d.reason = f"Merged into {merged_into_key}" if merged_into_key else REASONS["canceled"]
        return d
    if not links:
        if task["status"] == "done" and not task.get("done_confirmed_at"):
            d.status, d.flags, d.reason = "review", ["awaiting_confirmation"], REASONS["awaiting_confirmation"]
        else:
            d.status, d.reason = task["status"], REASONS["manual"]
        return d
    blocked = [i for i, c in zip(links, cats) if c == "blocked"]
    if blocked:
        d.flags.append("blocked")
        if any(i.get("blocked_reason") == "needs_input" for i in blocked):
            d.flags.append("blocked_needs_input")
    if any(_merged_not_live(i) for i in links):
        d.flags.append("merged_not_live")
    if "in_progress" in cats:
        d.status, d.reason = "in_progress", REASONS["in_progress"]
    elif "review" in cats:
        mnl = any(c == "review" and _merged_not_live(i) for i, c in zip(links, cats))
        d.status, d.reason = "review", REASONS["merged_not_live" if mnl else "review"]
    elif all(c == "done" for c in cats):
        d.status, d.reason = "done", REASONS["done"]
    elif blocked:
        d.status, d.reason = "in_progress", REASONS["blocked"]
    else:
        d.status, d.reason = "todo", REASONS["todo"]
    return d


def derive_epic(epic: dict, tasks: list[TaskDerived], now: int) -> Derived:
    """The epic column over its derived tasks (spec "Epics on top of tasks")."""
    live = [t for t in tasks if t.status != "canceled"]
    stats = [t.status for t in live]
    d = Derived("todo", done=stats.count("done"), total=len(live))

    if epic["manual_column"] == "canceled":
        d.board_column = "canceled"
        d.hidden = True
        return d

    flags: list[str] = []
    for t in live:
        for f in t.flags:
            if f not in flags:
                flags.append(f)

    confirmed = bool(epic.get("done_confirmed_at"))
    if "in_progress" in stats:
        col = "in_progress"
    elif "review" in stats:
        col = "review"
    elif live and all(s == "done" for s in stats):
        col = "done"
    elif not live and confirmed:
        col = "done"
    else:
        col = epic["manual_column"]
    d.board_column = col

    if col == "todo" and epic.get("stage") in ("spec", "plan") and _human(epic.get("waiting_on")):
        flags.append("awaiting_approval")
    if col == "review":
        human = any(t.status == "review" and ("awaiting_confirmation" in t.flags or _human(t.waiting_on))
                    for t in live)
        d.review_owner = "human" if human else "agent"
    d.flags = flags
    d.hidden = bool(col == "done" and epic.get("done_at")
                    and now - epic["done_at"] > DONE_HIDE_SECONDS)
    return d


def open_items(items: list[dict]) -> list[dict]:
    return [i for i in items if i.get("filing") != "ignored"
            and effective_category(i) in OPEN_CATEGORIES]
