import pytest

from loopboard.derive import TaskDerived, derive_epic, derive_task, effective_category
from loopboard.model import DAY

NOW = 1_800_000_000


def it(cat, *, merged=None, live=None, waiting="agent:hermes", blocked=None, filing="epic"):
    return {"status_category": cat, "filing": filing, "merged_at": merged, "live_at": live,
            "waiting_on": waiting, "blocked_reason": blocked}


def tk(status="todo", *, waiting="agent:hermes", confirmed=None):
    return {"id": 1, "status": status, "waiting_on": waiting, "done_confirmed_at": confirmed}


def ep(manual="todo", *, stage="build", waiting=None, confirmed=None, done_at=None):
    return {"manual_column": manual, "stage": stage, "waiting_on": waiting,
            "done_confirmed_at": confirmed, "done_at": done_at}


def one_task_per_item(items):
    # as the 0002 backfill does: an item canceled at its source gives a canceled task
    return [derive_task(tk("canceled" if i["status_category"] == "canceled" else "todo",
                           waiting=i["waiting_on"]), [i]) for i in items]


# --- derive_task: one test per lifecycle line of the spec ---

def test_task_in_progress_when_any_link_running():
    d = derive_task(tk(), [it("in_progress"), it("review"), it("done")])
    assert (d.status, d.reason) == ("in_progress", "In progress: a linked item is running")
    assert (d.linked, d.links_done, d.links_total) == (True, 1, 3)


def test_task_review_when_link_in_review():
    d = derive_task(tk(), [it("review"), it("done")])
    assert (d.status, d.flags, d.reason) == ("review", [], "Review: a linked item is in review")


def test_task_review_when_link_merged_not_live():
    d = derive_task(tk(), [it("review", merged=1)])
    assert d.status == "review"
    assert "merged_not_live" in d.flags
    assert d.reason == "Review: a linked PR is merged but not live yet"


def test_task_done_when_merged_pr_is_live():
    d = derive_task(tk(), [it("review", merged=1, live=2)])
    assert (d.status, d.reason) == ("done", "Done: every linked item is done")


def test_task_done_when_kanban_card_done():
    d = derive_task(tk(), [it("done")])
    assert (d.status, d.flags, d.reason) == ("done", [], "Done: every linked item is done")
    assert (d.links_done, d.links_total) == (1, 1)


def test_task_blocked_only_is_in_progress_with_flag():
    d = derive_task(tk(), [it("blocked", blocked="needs_input"), it("todo")])
    assert d.status == "in_progress"
    assert d.flags == ["blocked", "blocked_needs_input"]
    assert d.reason == "In progress: a linked item is blocked"


def test_blocked_link_flags_a_running_task():
    d = derive_task(tk(), [it("blocked"), it("in_progress")])
    assert (d.status, d.flags) == ("in_progress", ["blocked"])


def test_task_todo_when_links_not_started():
    d = derive_task(tk("done", confirmed=5), [it("backlog"), it("todo"), it("done")])
    assert (d.status, d.reason) == ("todo", "Todo: linked items haven't started")


def test_task_all_links_canceled_falls_back_to_manual():
    d = derive_task(tk("in_progress"), [it("canceled"), it("in_progress", filing="ignored")])
    assert (d.status, d.reason, d.linked) == ("in_progress", "Moved by hand", False)
    assert (d.links_done, d.links_total) == (0, 0)


def test_task_without_links_uses_manual_status():
    for s in ("todo", "in_progress", "review"):
        assert derive_task(tk(s), []).status == s
    assert derive_task(tk(), []).reason == "Moved by hand"


def test_task_manual_done_unconfirmed_is_review_awaiting_confirmation():
    d = derive_task(tk("done"), [])
    assert (d.status, d.flags) == ("review", ["awaiting_confirmation"])
    assert d.reason == "Done by an agent; waiting for a human to confirm"


def test_task_manual_done_confirmed_is_done():
    d = derive_task(tk("done", confirmed=5), [])
    assert (d.status, d.flags, d.reason) == ("done", [], "Moved by hand")


def test_canceled_wins_over_links():
    d = derive_task(tk("canceled"), [it("in_progress")])
    assert (d.status, d.reason, d.flags) == ("canceled", "Canceled", [])
    m = derive_task(tk("canceled"), [], merged_into_key="DEMO-7")
    assert m.reason == "Merged into DEMO-7"


# --- derive_epic over tasks ---

def td(status, flags=(), waiting="agent:a"):
    return TaskDerived(status=status, flags=list(flags), reason="", linked=False, links_done=0,
                       links_total=0, waiting_on=waiting)


def test_epic_column_from_tasks():
    d = derive_epic(ep(), [td("review"), td("done")], NOW)
    assert d.board_column == "review"
    assert (d.done, d.total) == (1, 2)
    assert d.review_owner == "agent"


def test_epic_review_owner_human_when_task_waits_on_human_or_awaits_confirmation():
    assert derive_epic(ep(), [td("review", waiting="human:owner")], NOW).review_owner == "human"
    d = derive_epic(ep(), [td("review", ["awaiting_confirmation"])], NOW)
    assert d.review_owner == "human" and "awaiting_confirmation" in d.flags


def test_epic_done_when_all_tasks_done_without_code():
    d = derive_epic(ep(), [td("done"), td("done"), td("canceled")], NOW)
    assert (d.board_column, d.done, d.total) == ("done", 2, 2)


def test_epic_no_tasks_confirmed_is_done():
    assert derive_epic(ep(confirmed=5), [], NOW).board_column == "done"
    assert derive_epic(ep("backlog"), [], NOW).board_column == "backlog"
    assert derive_epic(ep(confirmed=5), [td("canceled")], NOW).board_column == "done"


def test_epic_flags_are_union_of_task_flags():
    d = derive_epic(ep(), [td("in_progress", ["blocked"]), td("review", ["merged_not_live"]),
                           td("in_progress", ["blocked", "blocked_needs_input"])], NOW)
    assert d.board_column == "in_progress"
    assert d.flags == ["blocked", "merged_not_live", "blocked_needs_input"]


def test_epic_todo_tasks_keep_manual_column():
    assert derive_epic(ep("backlog"), [td("todo"), td("done")], NOW).board_column == "backlog"


# Old item-based expectations, now fed one task per item.
CASES = [
    ("running", ep(), [it("in_progress")], "in_progress", [], None),
    ("running beats review", ep(), [it("in_progress"), it("review")], "in_progress", [], None),
    ("review agent", ep(), [it("review")], "review", [], "agent"),
    ("review human", ep(), [it("review", waiting="human:owner")], "review", [], "human"),
    ("merged not live", ep(), [it("review", merged=1, waiting="human:owner")], "review",
     ["merged_not_live"], "human"),
    ("merged and live", ep(), [it("review", merged=1, live=2)], "done", [], None),
    ("all done with code", ep(), [it("done", merged=1, live=2), it("done")], "done", [], None),
    ("done no code", ep(), [it("done")], "done", [], None),
    ("done merged not live", ep(), [it("done", merged=1)], "done", ["merged_not_live"], None),
    ("done confirmed", ep(confirmed=5), [it("done")], "done", [], None),
    ("empty todo", ep("todo"), [], "todo", [], None),
    ("empty backlog", ep("backlog"), [], "backlog", [], None),
    ("canceled", ep("canceled"), [], "canceled", [], None),
    ("done plus canceled", ep(), [it("done", merged=1, live=2), it("canceled")], "done", [], None),
    ("blocked", ep(), [it("blocked")], "in_progress", ["blocked"], None),
    ("blocked needs input", ep(), [it("blocked", blocked="needs_input")], "in_progress",
     ["blocked", "blocked_needs_input"], None),
    ("awaiting approval", ep("todo", stage="spec", waiting="human:owner"), [], "todo",
     ["awaiting_approval"], None),
]


@pytest.mark.parametrize("name,epic,items,column,flags,owner", CASES, ids=[c[0] for c in CASES])
def test_derive_table(name, epic, items, column, flags, owner):
    d = derive_epic(epic, one_task_per_item(items), NOW)
    assert d.board_column == column
    assert set(flags) <= set(d.flags)
    if not flags:
        assert d.flags == []
    assert d.review_owner == owner
    if column == "canceled":
        assert d.hidden is True


def test_progress_counts_done_over_non_canceled():
    d = derive_epic(ep(), one_task_per_item([it("done", merged=1, live=2), it("todo")])
                    + [td("canceled")], NOW)
    assert (d.done, d.total) == (1, 2)


def test_effective_category_needs_live_for_done():
    assert effective_category(it("review", merged=1)) == "review"
    assert effective_category(it("review", merged=1, live=2)) == "done"


def test_done_hidden_only_after_seven_days():
    tasks = one_task_per_item([it("done", merged=1, live=2)])
    assert derive_epic(ep(done_at=NOW - 7 * DAY), tasks, NOW).hidden is False
    assert derive_epic(ep(done_at=NOW - 7 * DAY - 1), tasks, NOW).hidden is True
