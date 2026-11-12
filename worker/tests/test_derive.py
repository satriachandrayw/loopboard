import pytest

from loopboard.derive import derive_epic, effective_category
from loopboard.model import DAY

NOW = 1_800_000_000


def it(cat, *, merged=None, live=None, waiting="agent:hermes", blocked=None, filing="epic"):
    return {"status_category": cat, "filing": filing, "merged_at": merged, "live_at": live,
            "waiting_on": waiting, "blocked_reason": blocked}


def ep(manual="todo", *, stage="build", waiting=None, confirmed=None, done_at=None):
    return {"manual_column": manual, "stage": stage, "waiting_on": waiting,
            "done_confirmed_at": confirmed, "done_at": done_at}


CASES = [
    ("running", ep(), [it("in_progress")], "in_progress", [], None),
    ("running beats review", ep(), [it("in_progress"), it("review")], "in_progress", [], None),
    ("review agent", ep(), [it("review")], "review", [], "agent"),
    ("review human", ep(), [it("review", waiting="human:owner")], "review", [], "human"),
    ("merged not live", ep(), [it("review", merged=1, waiting="human:owner")], "review",
     ["merged_not_live"], "human"),
    ("merged and live", ep(), [it("review", merged=1, live=2)], "done", [], None),
    ("all done with code", ep(), [it("done", merged=1, live=2), it("done")], "done", [], None),
    ("done no code", ep(), [it("done")], "review", ["awaiting_confirmation"], "human"),
    ("done merged not live", ep(), [it("done", merged=1)], "done", ["merged_not_live"], None),
    ("done confirmed", ep(confirmed=5), [it("done")], "done", [], None),
    ("empty todo", ep("todo"), [], "todo", [], None),
    ("empty backlog", ep("backlog"), [], "backlog", [], None),
    ("canceled", ep("canceled"), [], "canceled", [], None),
    ("done plus canceled", ep(), [it("done", merged=1, live=2), it("canceled")], "done", [], None),
    ("blocked", ep(), [it("blocked")], "todo", ["blocked"], None),
    ("blocked needs input", ep(), [it("blocked", blocked="needs_input")], "todo",
     ["blocked", "blocked_needs_input"], None),
    ("awaiting approval", ep("todo", stage="spec", waiting="human:owner"), [], "todo",
     ["awaiting_approval"], None),
    ("ignored", ep(), [it("in_progress", filing="ignored")], "todo", [], None),
]


@pytest.mark.parametrize("name,epic,items,column,flags,owner", CASES, ids=[c[0] for c in CASES])
def test_derive_table(name, epic, items, column, flags, owner):
    d = derive_epic(epic, items, NOW)
    assert d.board_column == column
    assert set(flags) <= set(d.flags)
    if not flags:
        assert d.flags == []
    assert d.review_owner == owner
    if column == "canceled":
        assert d.hidden is True


def test_progress_counts_done_over_non_canceled():
    d = derive_epic(ep(), [it("done", merged=1, live=2), it("todo"), it("canceled")], NOW)
    assert (d.done, d.total) == (1, 2)


def test_effective_category_needs_live_for_done():
    assert effective_category(it("review", merged=1)) == "review"
    assert effective_category(it("review", merged=1, live=2)) == "done"


def test_done_hidden_only_after_seven_days():
    items = [it("done", merged=1, live=2)]
    assert derive_epic(ep(done_at=NOW - 7 * DAY), items, NOW).hidden is False
    assert derive_epic(ep(done_at=NOW - 7 * DAY - 1), items, NOW).hidden is True
