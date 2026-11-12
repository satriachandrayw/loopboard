"""Derived epic column, flags and progress (D5-D8)."""
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


def derive_epic(epic: dict, items: list[dict], now: int) -> Derived:
    live_items = [i for i in items if i.get("filing") != "ignored"]
    tasks = [(i, effective_category(i)) for i in live_items if i["status_category"] != "canceled"]
    cats = [c for _, c in tasks]
    done = sum(1 for c in cats if c == "done")
    has_code = any(i.get("merged_at") for i, _ in tasks)
    d = Derived("todo", done=done, total=len(tasks), has_code=has_code)

    if epic["manual_column"] == "canceled":
        d.board_column = "canceled"
        d.hidden = True
        return d

    flags: list[str] = []
    blocked = [i for i, c in tasks if c == "blocked"]
    if blocked:
        flags.append("blocked")
        if any(i.get("blocked_reason") == "needs_input" for i in blocked):
            flags.append("blocked_needs_input")
    if any(i.get("merged_at") and not i.get("live_at") for i, _ in tasks):
        flags.append("merged_not_live")

    confirmed = bool(epic.get("done_confirmed_at"))
    awaiting_confirmation = False
    if "in_progress" in cats:
        col = "in_progress"
    elif "review" in cats:
        col = "review"
    elif tasks and all(c == "done" for c in cats):
        if has_code or confirmed:
            col = "done"
        else:
            col = "review"
            awaiting_confirmation = True
    elif not tasks and confirmed:
        col = "done"
    else:
        col = epic["manual_column"]
    d.board_column = col

    if awaiting_confirmation:
        flags.append("awaiting_confirmation")
    if col == "todo" and epic.get("stage") in ("spec", "plan") and _human(epic.get("waiting_on")):
        flags.append("awaiting_approval")
    if col == "review":
        human = awaiting_confirmation or any(
            c == "review" and _human(i.get("waiting_on")) for i, c in tasks)
        d.review_owner = "human" if human else "agent"
    d.flags = flags
    d.hidden = bool(col == "done" and epic.get("done_at")
                    and now - epic["done_at"] > DONE_HIDE_SECONDS)
    return d


def open_items(items: list[dict]) -> list[dict]:
    return [i for i in items if i.get("filing") != "ignored"
            and effective_category(i) in OPEN_CATEGORIES]
