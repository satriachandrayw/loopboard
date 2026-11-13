import pytest

from loopboard_connectors.contract import split_epic_prefix


@pytest.mark.parametrize("title,key,rest", [
    ("[DEMO-E5] Add checkout retry", "DEMO-E5", "Add checkout retry"),
    ("[DEMO-E5]Add checkout retry", "DEMO-E5", "Add checkout retry"),
    ("\t [X1-E0]  y", "X1-E0", "y"),
    ("[ABCDEFGHIJ-E123] long project key", "ABCDEFGHIJ-E123", "long project key"),
])
def test_title_prefix_sets_epic_key_and_strips_title(title, key, rest):
    assert split_epic_prefix(title) == (key, rest)


@pytest.mark.parametrize("title", [
    "Add checkout retry [DEMO-E5]",
    "Fix [DEMO-E5] Add checkout retry",
    "fix: [DEMO-E5] retry",
])
def test_prefix_only_at_start(title):
    assert split_epic_prefix(title) == (None, title)


@pytest.mark.parametrize("title", [
    "[demo-e5] lowercase",
    "[Demo-E5] mixed case",
    "[DEMO-e5] lowercase e",
    "[DEMO-E] no number",
    "[DEMO5] no epic part",
    "[D-E5] project key too short",
    "[ABCDEFGHIJK-E5] project key too long",
    "[1DEMO-E5] starts with a digit",
    "[DEMO-E5 ] space inside",
    "(DEMO-E5) wrong brackets",
    "[DEMO-E5]",
    "",
])
def test_malformed_or_lowercase_prefix_ignored(title):
    assert split_epic_prefix(title) == (None, title)


@pytest.mark.parametrize("title,epic,task,rest", [
    ("[DEMO-E5] Add retry", "DEMO-E5", None, "Add retry"),
    ("[DEMO-12] Add retry", None, "DEMO-12", "Add retry"),
    ("[DEMO-12]Add retry", None, "DEMO-12", "Add retry"),
    (" [X1-0]  y", None, "X1-0", "y"),
    ("fix(OPS-8001): retry", None, None, "fix(OPS-8001): retry"),
    ("Add retry [DEMO-12]", None, None, "Add retry [DEMO-12]"),
    ("[demo-12] lowercase", None, None, "[demo-12] lowercase"),
    ("[DEMO-12]", None, None, "[DEMO-12]"),
    ("[DEMO-1E2] odd", None, None, "[DEMO-1E2] odd"),
])
def test_split_key_prefix_task_and_epic(title, epic, task, rest):
    from loopboard_connectors.contract import split_key_prefix

    assert split_key_prefix(title) == (epic, task, rest)


def test_item_payload_carries_task_key_only_when_set():
    from loopboard_connectors.contract import Item

    base = dict(source="kanban", external_id="1", title="t", url=None, status_category="todo", raw_status="todo",
                owner=None, waiting_on="agent:a", blocked_reason=None, next_step=None, project_key="DEMO",
                epic_key=None, last_activity_at="2026-11-12T00:00:00Z")
    assert "task_key" not in Item(**base).to_payload()
    assert Item(**base, task_key="DEMO-3").to_payload()["task_key"] == "DEMO-3"
