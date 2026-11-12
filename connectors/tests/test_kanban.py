import copy
import json
from pathlib import Path

import pytest

from loopboard_connectors import kanban
from loopboard_connectors.contract import SourceError

FIX = Path(__file__).parent / "fixtures" / "kanban"
TENANTS = {"demo": "DEMO"}


def load(name):
    return json.loads((FIX / name).read_text())


def item_for(i):
    show = load(f"show-{i}.json")
    return kanban.map_task(show["task"], show, human="owner", tenants=TENANTS)


def mk(status, assignee="builder", **kw):
    task = {"id": 99, "title": "T", "status": status, "assignee": assignee, "tenant": "demo",
            "created_at": 1762900000, "started_at": None, "completed_at": None}
    task.update(kw)
    return task, {"task": task, "events": []}


@pytest.mark.parametrize("i,cat,waiting,reason,owner", [
    (1, "todo", "human:owner", None, None),
    (2, "todo", "agent:builder", None, "agent:builder"),
    (3, "in_progress", "agent:builder", None, "agent:builder"),
    (4, "review", "human:owner", None, "agent:builder"),
    (5, "blocked", "human:owner", "needs_input", "agent:builder"),
    (6, "blocked", "source:kanban", "other", "agent:builder"),
    (7, "done", None, None, "agent:builder"),
    (8, "canceled", None, None, "agent:builder"),
])
def test_status_mapping(i, cat, waiting, reason, owner):
    it = item_for(i)
    assert (it.status_category, it.waiting_on) == (cat, waiting)
    assert it.blocked_reason == reason
    assert it.owner == owner
    assert it.next_step is None and it.url is None and it.source == "kanban"


def test_ready_and_unassigned_todo():
    t, s = mk("ready")
    it = kanban.map_task(t, s, human="owner", tenants=TENANTS)
    assert (it.status_category, it.waiting_on) == ("todo", "agent:builder")
    t, s = mk("todo", assignee=None)
    it = kanban.map_task(t, s, human="owner", tenants=TENANTS)
    assert (it.status_category, it.waiting_on, it.owner) == ("todo", "source:kanban", None)


def test_unknown_status_is_source_error():
    t, s = mk("weird")
    with pytest.raises(SourceError):
        kanban.map_task(t, s, human="owner", tenants=TENANTS)


def test_tenant_maps_to_project_key():
    assert item_for(2).project_key == "DEMO"
    t, s = mk("todo", tenant="other")
    assert kanban.map_task(t, s, human="owner", tenants=TENANTS).project_key is None


def test_last_activity_uses_latest_event():
    t, s = mk("todo")
    s["events"] = [{"kind": "x", "payload": {}, "created_at": 1762999999}]
    it = kanban.map_task(t, s, human="owner", tenants=TENANTS)
    assert it.last_activity_at == "2025-11-13T02:13:19Z"


def test_epoch_timestamps_emitted_as_utc_iso():
    t, s = mk("todo", created_at=0)
    assert kanban.map_task(t, s, human="owner", tenants=TENANTS).last_activity_at == "1970-01-01T00:00:00Z"


def test_free_text_never_in_payload():
    for i in range(1, 9):
        assert "SECRET-BODY" not in json.dumps(item_for(i).to_payload())


def test_block_kind_from_newest_blocked_event():
    assert item_for(5).blocked_reason == "needs_input"  # older event is transient
    t, s = mk("blocked")
    s["events"] = [
        {"kind": "blocked", "payload": {"kind": "needs_input"}, "created_at": 10},
        {"kind": "blocked", "payload": {"kind": "transient"}, "created_at": 20},
    ]
    assert kanban.map_task(t, s, human="owner", tenants=TENANTS).blocked_reason == "other"


def test_collect_replay_matches_expected_board():
    exp = load("expected-board.json")
    items = kanban.collect(kanban.replay_runner(FIX), human="owner", tenants=TENANTS, board=None)
    cats = {}
    for it in items:
        cats[it.status_category] = cats.get(it.status_category, 0) + 1
    assert cats == exp["categories"]
    assert sum(1 for it in items if it.status_category != "canceled") == exp["unfiled"]


def test_one_show_failure_fails_whole_run():
    base = kanban.replay_runner(FIX)

    def run(argv):
        if argv[-2:] == ["5", "--json"] or ("show" in argv and "5" in argv):
            raise SourceError("boom")
        return base(argv)

    with pytest.raises(SourceError):
        kanban.collect(run, human="owner", tenants=TENANTS, board=None)


def test_missing_field_fails_run():
    lst = load("list.json")
    del lst[0]["status"]
    base = kanban.replay_runner(FIX)

    def run(argv):
        return json.dumps(lst) if "list" in argv else base(argv)

    with pytest.raises(SourceError):
        kanban.collect(run, human="owner", tenants=TENANTS, board=None)


def test_board_flag_and_argv():
    seen = []
    base = kanban.replay_runner(FIX)

    def run(argv):
        seen.append(argv)
        return base(argv)

    kanban.collect(run, human="owner", tenants=TENANTS, board="b1")
    assert seen[0] == ["hermes", "kanban", "--board", "b1", "list", "--json"]
    assert seen[1][:5] == ["hermes", "kanban", "--board", "b1", "show"]


def test_replay_missing_file(tmp_path):
    with pytest.raises(SourceError):
        kanban.replay_runner(tmp_path)(["hermes", "kanban", "list", "--json"])


import pytest as _pt


@_pt.mark.parametrize("mutate", [
    lambda s: s.update(events=None),
    lambda s: s.update(events=["x"]),
    lambda s: s.update(events=[{"kind": "blocked", "payload": "str", "created_at": 5}]),
    lambda s: s.update(events=[{"kind": "blocked", "payload": {}}]),
    lambda s: s.update(events=[{"kind": "blocked", "payload": {}, "created_at": "abc"}]),
])
def test_malformed_events_fail_run(mutate):
    base = kanban.replay_runner(FIX)

    def run(argv):
        out = base(argv)
        if "show" in argv:
            s = json.loads(out)
            s["task"]["status"] = "blocked"
            mutate(s)
            return json.dumps(s)
        return out

    with pytest.raises(SourceError):
        kanban.collect(run, human="owner", tenants=TENANTS, board=None)


def test_replay_with_board_arg():
    run = kanban.replay_runner(FIX)
    assert json.loads(run(["hermes", "kanban", "--board", "b", "list", "--json"]))
    assert json.loads(run(["hermes", "kanban", "--board", "b", "show", "2", "--json"]))["task"]["id"] == 2
    with pytest.raises(SourceError):
        run(["hermes", "kanban", "--board", "show", "--json"])


def test_long_title_truncated_to_300():
    t, s = mk("todo", title="x" * 301)
    assert len(kanban.map_task(t, s, human="owner", tenants=TENANTS).title) == 300


@pytest.mark.parametrize("bad", ["two words", "a" * 65, "bad/char", "x\n"])
def test_invalid_assignee_falls_back(bad):
    for status in ("todo", "running", "review", "done"):
        t, s = mk(status, assignee=bad)
        it = kanban.map_task(t, s, human="owner", tenants=TENANTS)
        assert it.owner is None
        assert it.waiting_on in (None, "human:owner", "source:kanban")
    t, s = mk("running", assignee=bad)
    assert kanban.map_task(t, s, human="owner", tenants=TENANTS).waiting_on == "source:kanban"
