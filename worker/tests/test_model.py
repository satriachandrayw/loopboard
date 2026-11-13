import pytest

from loopboard.model import ValidationError, parse_ts


def test_parse_ts_offset_to_utc():
    assert parse_ts("2026-11-12T09:00:00+07:00") == parse_ts("2026-11-12T02:00:00Z")


def test_parse_ts_naive_rejected():
    with pytest.raises(ValidationError):
        parse_ts("2026-11-12T09:00:00")


def test_parse_ts_garbage_rejected():
    with pytest.raises(ValidationError):
        parse_ts("not a time")


def test_parse_ts_out_of_range_rejected():
    import pytest

    from loopboard.model import ValidationError, parse_ts

    for s in ("9999-12-31T23:59:59-14:00", "0001-01-01T00:00:00+14:00"):
        with pytest.raises(ValidationError):
            parse_ts(s)


def test_item_url_must_be_http_or_https():
    from pydantic import ValidationError as PydanticError

    from loopboard.model import ItemIn

    base = dict(external_id="1", title="t", status_category="done", last_activity_at="2026-11-12T00:00:00Z")
    assert ItemIn(**base, url="https://example.com/x").url == "https://example.com/x"
    for bad in ("data:text/html,x", "javascript:alert(1)", "example.com"):
        with pytest.raises(PydanticError):
            ItemIn(**base, url=bad)


def test_epic_goal_required_and_stripped():
    from loopboard.model import EpicIn, EpicPatch

    assert EpicIn(title="T", waiting_on="agent:a", goal="  Ship it  ").goal == "Ship it"
    for bad in (None, "", "   ", "x" * 2001):
        with pytest.raises(ValueError):
            EpicIn(title="T", waiting_on="agent:a", goal=bad)
    with pytest.raises(ValueError):
        EpicIn(title="T", waiting_on="agent:a")
    assert EpicPatch(goal=" New ").goal == "New"
    assert "goal" not in EpicPatch().model_fields_set
    for bad in ("", "   "):
        with pytest.raises(ValueError):
            EpicPatch(goal=bad)


def _task(**kw):
    base = dict(summary="Ship", description="What it is", done_when="It is live", owner="coder",
                waiting_on="agent:coder")
    return {**base, **kw}


def test_task_in_defaults_and_strips():
    from loopboard.model import TaskIn

    t = TaskIn(**_task(summary="  Ship it  ", refs=[" OPS-8001 "]))
    assert (t.summary, t.type, t.priority, t.epic_key, t.item_id) == ("Ship it", "task", "medium", None, None)
    assert t.refs == ["OPS-8001"]


def test_task_in_blanks_and_limits():
    from loopboard.model import TaskIn

    for field, bad in [("summary", "   "), ("summary", "x" * 301), ("description", " "),
                       ("description", "x" * 2001), ("done_when", "  "), ("done_when", "x" * 301),
                       ("owner", " "), ("owner", "x" * 101), ("type", "story"), ("priority", "urgent"),
                       ("waiting_on", "nobody"), ("epic_key", "DEMO-1"), ("refs", ["OPS"]),
                       ("refs", ["ops-1"]), ("refs", [f"OPS-{n}" for n in range(11)])]:
        with pytest.raises(ValueError):
            TaskIn(**_task(**{field: bad}))
    assert TaskIn(**_task(summary="x" * 300, refs=[f"OPS-{n}" for n in range(10)])).refs[9] == "OPS-9"


def test_task_in_requires_waiting_on_and_text_fields():
    from loopboard.model import TaskIn

    for missing in ("summary", "description", "done_when", "owner", "waiting_on"):
        body = _task()
        del body[missing]
        with pytest.raises(ValueError):
            TaskIn(**body)


def test_task_patch_status_link_merge_models():
    from loopboard.model import ItemIn, LinkIn, MergeIn, TaskPatch, TaskStatusIn

    p = TaskPatch(epic_key=None)
    assert p.model_fields_set == {"epic_key"} and p.epic_key is None
    with pytest.raises(ValueError):
        TaskPatch(description="  ")
    assert TaskStatusIn(status="done").status == "done"
    with pytest.raises(ValueError):
        TaskStatusIn(status="blocked")
    assert LinkIn(task_key="DEMO-12").task_key == "DEMO-12"
    for bad in ("DEMO-E1", "demo-1"):
        with pytest.raises(ValueError):
            LinkIn(task_key=bad)
        with pytest.raises(ValueError):
            MergeIn(into=bad)
    base = dict(external_id="1", title="t", status_category="done", last_activity_at="2026-11-12T00:00:00Z")
    assert ItemIn(**base, task_key="DEMO-3").task_key == "DEMO-3"
    with pytest.raises(ValueError):
        ItemIn(**base, task_key="DEMO-E3")
