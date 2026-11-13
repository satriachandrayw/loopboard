import json

import pytest

from loopboard import reads
from loopboard.db import Repo
from tests.fakes.d1 import FakeD1

NOW = 1_800_000_000


async def seeded_0001():
    db = FakeD1()
    db.apply_migrations(upto="0001_init.sql")
    repo = Repo(db)
    for key in ("DEMO", "SAMPLE"):
        await repo.execute("insert into projects(key,name,created_at) values(?,?,1)", (key, key))

    async def epic(pid, seq, key, manual="todo"):
        return await repo.execute(
            "insert into epics(project_id,seq,key,title,goal,manual_column,board_column,stage,waiting_on,"
            "last_activity_at,created_at,updated_at) values(?,?,?,?,?,?,?,'build','agent:a',?,1,1)",
            (pid, seq, key, key, "g", manual, manual, NOW - 10))

    e1 = await epic(1, 1, "DEMO-E1")
    e2 = await epic(1, 2, "DEMO-E2", "canceled")
    s1 = await epic(2, 1, "SAMPLE-E1")

    async def item(ext, *, epic_id=None, project_id=None, filing, cat="todo", merged=None, owner=None,
                   source="kanban", url=None):
        return await repo.execute(
            "insert into items(source,external_id,project_id,epic_id,filing,title,url,status_category,owner,"
            "waiting_on,merged_at,last_activity_at,created_at,updated_at)"
            " values(?,?,?,?,?,?,?,?,?,'agent:a',?,?,?,?)",
            (source, ext, project_id, epic_id, filing, f"title {ext}", url, cat, owner, merged,
             NOW - 100, 5, 6))

    await item("1", epic_id=e1, project_id=1, filing="epic", cat="todo", owner="coder")
    await item("2", epic_id=s1, project_id=2, filing="epic", cat="done")
    await item("3", epic_id=e1, project_id=1, filing="epic", cat="review", merged=NOW - 50,
               source="github", url="https://example.test/pr/3")
    await item("4", project_id=1, filing="standalone", cat="in_progress", owner="  ")
    await item("5", project_id=1, filing="unfiled")
    await item("6", project_id=1, filing="ignored")
    await item("7", epic_id=e2, project_id=1, filing="epic", cat="in_progress")
    await item("8", epic_id=s1, project_id=2, filing="epic", cat="todo")
    await item("9", epic_id=s1, project_id=2, filing="epic", cat="canceled")
    return db, repo


def migrate(db):
    db.apply_migrations(upto="0002_tasks.sql")


def board_shape(b):
    return {c["column"]: sorted((x["key"], x["progress"]["done"], x["progress"]["total"], tuple(x["flags"]))
                                for x in c["cards"]) for c in b["columns"]}


async def test_0002_backfills_one_task_per_filed_item():
    db, repo = await seeded_0001()
    migrate(db)
    tasks = await repo.query("select * from tasks order by id")
    by_item = {t["origin_item_id"]: t for t in tasks}
    assert sorted(by_item) == [1, 2, 3, 4, 7, 8, 9]
    assert [t["key"] for t in tasks if t["project_id"] == 1] == ["DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4"]
    assert [by_item[i]["key"] for i in (1, 3, 4, 7)] == ["DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4"]
    assert [by_item[i]["key"] for i in (2, 8, 9)] == ["SAMPLE-1", "SAMPLE-2", "SAMPLE-3"]
    assert by_item[9]["status"] == "canceled"
    for t in tasks:
        assert t["reporter"] == "migration" and t["status"] == ("canceled" if t["id"] == by_item[9]["id"] else "todo")
        assert t["description"].startswith("Migrated from ")
        assert t["done_when"] == "The linked work is live."
        assert (t["type"], t["priority"], t["refs"]) == ("task", "medium", "[]")
    assert by_item[3]["description"] == "Migrated from https://example.test/pr/3"
    assert by_item[1]["description"] == "Migrated from kanban:1"
    assert by_item[1]["owner"] == "coder" and by_item[4]["owner"] == "kanban"
    assert by_item[4]["epic_id"] is None and by_item[1]["epic_id"] == 1
    assert by_item[1]["summary"] == "title 1" and by_item[1]["waiting_on"] == "agent:a"
    assert (by_item[1]["created_at"], by_item[1]["updated_at"]) == (5, 6)
    assert by_item[1]["last_activity_at"] == NOW - 100
    items = {i["id"]: i for i in await repo.query("select * from items")}
    for iid, t in by_item.items():
        assert items[iid]["task_id"] == t["id"]
    assert items[5]["task_id"] is None and items[6]["task_id"] is None
    evs = await repo.query("select * from events where kind = 'task.created' order by subject_id")
    assert [e["subject_id"] for e in evs] == [t["id"] for t in tasks]
    assert all(e["actor"] == "migration" and e["subject_type"] == "task" for e in evs)
    assert json.loads(evs[0]["payload"])["key"] == "DEMO-1"


async def test_0002_constraints_and_relations_accept_tasks():
    db, repo = await seeded_0001()
    await repo.execute("insert into relations(kind,from_type,from_id,to_type,to_id,created_at) "
                       "values('blocks','epic',1,'item',1,1)")
    migrate(db)
    assert len(await repo.query("select * from relations")) == 1
    await repo.execute("insert into relations(kind,from_type,from_id,to_type,to_id,created_at) "
                       "values('blocks','task',1,'task',2,1)")
    with pytest.raises(Exception):
        await repo.execute("update tasks set status = 'nope' where id = 1")
    with pytest.raises(Exception):
        await repo.execute("update tasks set seq = 2 where id = 1")
    with pytest.raises(Exception):
        await repo.execute("update tasks set type = 'story' where id = 1")


async def test_0002_backfill_keeps_board_unchanged():
    # `before` is what the item-based board (base commit) showed for this data; the epic rows
    # (column, done/total, flags) must read the same over the backfilled tasks.
    before = {"backlog": [], "todo": [("SAMPLE-E1", 1, 2, ())],
              "in_progress": [], "review": [("DEMO-E1", 0, 2, ("merged_not_live",))], "done": []}
    db, repo = await seeded_0001()
    migrate(db)
    assert board_shape(await reads.board(repo, now=NOW)) == before
    # after the migration the board reads tasks: removing the items' filing must not move it
    await repo.execute("update items set filing = 'unfiled', epic_id = null")
    assert board_shape(await reads.board(repo, now=NOW)) == before


async def _add_epic_with_items(repo, seq, key, manual, cats):
    eid = await repo.execute(
        "insert into epics(project_id,seq,key,title,goal,manual_column,board_column,stage,waiting_on,"
        "last_activity_at,created_at,updated_at) values(1,?,?,?,'g',?,?,'build','agent:a',?,1,1)",
        (seq, key, key, manual, manual, NOW - 10))
    for n, cat in enumerate(cats):
        await repo.execute(
            "insert into items(source,external_id,project_id,epic_id,filing,title,status_category,waiting_on,"
            "last_activity_at,created_at,updated_at) values('kanban',?,1,?,'epic','t',?,'agent:a',?,1,1)",
            (f"{key}-{n}", eid, cat, NOW - 100))


async def test_0002_board_changes_only_by_lifecycle_rules():
    """The owner accepted two board moves the task lifecycle makes; every other epic keeps its column."""
    db, repo = await seeded_0001()
    # (a) only a blocked Kanban card: was its manual column (todo), now In progress with `blocked`.
    await _add_epic_with_items(repo, 3, "DEMO-E3", "todo", ["blocked"])
    # (b) only done Kanban cards, no code: was Review awaiting confirmation, now Done.
    await _add_epic_with_items(repo, 4, "DEMO-E4", "todo", ["done", "done"])
    migrate(db)
    after = board_shape(await reads.board(repo, now=NOW))
    cards = {k: (col, d, t, flags) for col, xs in after.items() for (k, d, t, flags) in xs}
    assert cards["DEMO-E3"] == ("in_progress", 0, 1, ("blocked",))
    assert cards["DEMO-E4"] == ("done", 2, 2, ())
    # (c) the existing fixture's epics read as before
    assert cards["SAMPLE-E1"] == ("todo", 1, 2, ())
    assert cards["DEMO-E1"] == ("review", 0, 2, ("merged_not_live",))
    assert "DEMO-E2" not in cards

