from loopboard.derive import derive_epic
from loopboard.stall import epic_stalled, item_stalled, threshold_hours

NOW = 1_800_000_000
H = 3600


def it(cat="in_progress", source="kanban", age_h=0, filing="epic", **kw):
    return {"source": source, "filing": filing, "status_category": cat, "merged_at": None,
            "live_at": None, "last_activity_at": NOW - int(age_h * H), "waiting_on": "agent:x",
            "blocked_reason": None, **kw}


def ep(manual="todo", age_h=0):
    return {"manual_column": manual, "stage": "build", "waiting_on": None,
            "done_confirmed_at": None, "done_at": None, "last_activity_at": NOW - int(age_h * H)}


def stalled(epic, items, th=None):
    return epic_stalled(epic, items, derive_epic(epic, items, NOW), NOW, th or {})


def test_item_stalled_after_default_24h():
    assert item_stalled(it(age_h=24), NOW, {}) is False
    i = it()
    i["last_activity_at"] = NOW - 24 * H - 1
    assert item_stalled(i, NOW, {}) is True


def test_source_threshold_overrides_default():
    th = {"github": 4}
    assert item_stalled(it(source="github", age_h=5), NOW, th) is True
    assert item_stalled(it(source="kanban", age_h=5), NOW, th) is False
    assert threshold_hours(th, "kanban") == 24.0


def test_done_and_canceled_never_stalled():
    assert item_stalled(it("done", age_h=100), NOW, {}) is False
    assert item_stalled(it("canceled", age_h=100), NOW, {}) is False


def test_backlog_epic_never_stalled():
    assert stalled(ep("backlog", 100), []) is False


def test_epic_stalled_when_no_open_task_moved():
    assert stalled(ep(), [it(age_h=30)]) is True


def test_epic_not_stalled_when_an_open_task_moved_recently():
    assert stalled(ep(), [it(age_h=30), it(age_h=1)]) is False


def test_empty_todo_epic_uses_own_activity():
    assert stalled(ep(age_h=25), []) is True
    assert stalled(ep(age_h=24), []) is False
    e = ep(age_h=24)
    e["last_activity_at"] -= 1
    assert stalled(e, []) is True
    assert stalled(ep(age_h=1), []) is False


def test_epic_threshold_is_shortest_source():
    items = [it(source="github", age_h=5), it(source="kanban", age_h=5)]
    assert stalled(ep(), items, {"github": 4, "kanban": 24}) is True
