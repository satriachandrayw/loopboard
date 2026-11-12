import json

from loopboard.recompute import recompute_epic

NOW = 1_800_000_000


async def seed(repo, cat=None, merged=None, live=None, board="todo", done_at=None, confirmed=None):
    await repo.execute("insert into projects(key,name,created_at) values('DEMO','Demo',1)")
    await repo.execute(
        "insert into epics(project_id,seq,key,title,manual_column,board_column,stage,done_at,"
        "done_confirmed_at,last_activity_at,created_at,updated_at) "
        "values(1,1,'DEMO-E1','E','todo',?,'build',?,?,1,1,1)", (board, done_at, confirmed))
    if cat:
        await repo.execute(
            "insert into items(source,external_id,epic_id,filing,title,status_category,merged_at,"
            "live_at,last_activity_at,created_at,updated_at) values('kanban','1',1,'epic','t',?,?,?,1,1,1)",
            (cat, merged, live))


async def events(repo):
    return await repo.query("select * from events")


async def test_recompute_writes_column_and_one_event(repo):
    await seed(repo, "in_progress")
    col = await recompute_epic(repo, 1, actor="system", via="ingest", now=NOW)
    assert col == "in_progress"
    row = await repo.first("select board_column, updated_at from epics where id=1")
    assert row["board_column"] == "in_progress" and row["updated_at"] == NOW
    ev = await events(repo)
    assert len(ev) == 1
    e = ev[0]
    assert (e["kind"], e["subject_type"], e["subject_id"], e["actor"], e["via"]) == (
        "epic.column_changed", "epic", 1, "system", "ingest")
    assert json.loads(e["payload"]) == {"from": "todo", "to": "in_progress"}


async def test_no_event_when_column_unchanged(repo):
    await seed(repo, "in_progress", board="in_progress")
    assert await recompute_epic(repo, 1, actor="system", via="ingest", now=NOW) == "in_progress"
    assert await events(repo) == []


async def test_done_at_set_on_entering_done_and_cleared_on_leaving(repo):
    await seed(repo, "review", merged=1, live=2)
    assert await recompute_epic(repo, 1, actor="a", via="api", now=NOW) == "done"
    assert (await repo.first("select done_at from epics where id=1"))["done_at"] == NOW
    await repo.execute("update items set status_category='in_progress', live_at=null, merged_at=null")
    assert await recompute_epic(repo, 1, actor="a", via="api", now=NOW + 5) == "in_progress"
    assert (await repo.first("select done_at from epics where id=1"))["done_at"] is None
