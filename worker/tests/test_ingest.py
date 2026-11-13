import json

import pytest

from loopboard.model import parse_ts
from tests.test_auth import add_token, bearer

NOW = 1_800_000_000
T1 = "2026-11-12T09:00:00+07:00"
T2 = "2026-11-12T10:00:00+07:00"


def item(**over):
    d = dict(external_id="a", title="A", status_category="todo", waiting_on="agent:hermes",
             last_activity_at=T1)
    d.update(over)
    return d


async def setup(make_app, client_for, **tok):
    app, repo = make_app(clock=lambda: NOW)
    tok.setdefault("source", "kanban")
    t = await add_token(repo, name="bot", scopes="ingest", **tok)
    return app, repo, t


async def post(client_for, app, t, items, source="kanban"):
    async with client_for(app) as c:
        return await c.post("/api/ingest", json={"source": source, "items": items}, headers=bearer(t))


async def mk_epic(repo, key="DEMO-E1", pkey="DEMO"):
    pid = (await repo.first("select id from projects where key=?", (pkey,)))
    if pid is None:
        await repo.execute("insert into projects(key,name,created_at) values (?,?,1)", (pkey, pkey))
        pid = await repo.first("select id from projects where key=?", (pkey,))
    seq = int(key.split("-E")[1])
    return await repo.execute(
        "insert into epics(project_id,seq,key,title,manual_column,board_column,stage,last_activity_at,"
        "created_at,updated_at) values (?,?,?,?, 'todo','todo','idea',1,1,1)",
        (pid["id"], seq, key, key))


async def row(repo, ext="a"):
    return await repo.first("select * from items where external_id=?", (ext,))


async def events(repo, kind=None):
    return await repo.query("select * from events where subject_type='item' order by id")


async def test_ingest_creates_unfiled_item_with_created_event(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    r = await post(client_for, app, t, [item()])
    assert r.status_code == 200 and r.json()["created"] == 1
    assert (await row(repo))["filing"] == "unfiled"
    (e,) = await events(repo)
    assert (e["kind"], e["actor"], e["via"]) == ("item.created", "bot", "ingest")


async def test_epic_key_files_item_to_epic(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    eid = await mk_epic(repo)
    r = await post(client_for, app, t, [item(epic_key="DEMO-E1")])
    assert r.status_code == 200
    x = await row(repo)
    assert (x["filing"], x["epic_id"]) == ("epic", eid)
    assert x["project_id"] is not None


async def test_reingest_keeps_filing_and_epic(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    await mk_epic(repo)
    e2 = await mk_epic(repo, "DEMO-E2")
    e1 = (await repo.first("select id from epics where key='DEMO-E1'"))["id"]
    await post(client_for, app, t, [item(epic_key="DEMO-E1")])
    await repo.execute("update items set filing='standalone'")
    await post(client_for, app, t, [item(last_activity_at=T2)])
    x = await row(repo)
    assert (x["filing"], x["epic_id"]) == ("standalone", e1)
    await repo.execute("update items set filing='epic', epic_id=?", (e2,))
    await post(client_for, app, t, [item(last_activity_at="2026-11-12T11:00:00+07:00", title="B")])
    x = await row(repo)
    assert (x["filing"], x["epic_id"], x["title"]) == ("epic", e2, "B")


async def test_older_payload_does_not_regress_newer_state(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    await post(client_for, app, t, [item(status_category="done", waiting_on=None, last_activity_at=T2)])
    n = len(await events(repo))
    r = await post(client_for, app, t, [item(status_category="in_progress", last_activity_at=T1)])
    assert r.json()["skipped_older"] == 1
    x = await row(repo)
    assert (x["status_category"], x["last_activity_at"]) == ("done", parse_ts(T2))
    assert len(await events(repo)) == n


async def test_replayed_batch_is_idempotent(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    batch = [item(), item(external_id="b")]
    await post(client_for, app, t, batch)
    n = len(await events(repo))
    r = await post(client_for, app, t, batch)
    assert (r.json()["created"], r.json()["updated"]) == (0, 0)
    assert len(await events(repo)) == n


async def test_duplicate_in_batch_last_by_timestamp_wins(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    r = await post(client_for, app, t, [item(last_activity_at=T1), item(status_category="in_progress", last_activity_at=T2)])
    assert r.status_code == 200
    assert (await row(repo))["status_category"] == "in_progress"
    r = await post(client_for, app, t, [item(status_category="review", last_activity_at="2026-11-12T12:00:00+07:00"),
                                        item(last_activity_at=T1)])
    assert r.json()["skipped_older"] == 1
    assert (await row(repo))["status_category"] == "review"


async def test_offset_timestamp_normalised_to_utc(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    await post(client_for, app, t, [item()])
    assert (await row(repo))["last_activity_at"] == parse_ts("2026-11-12T02:00:00Z")


async def test_naive_timestamp_in_ingest_is_422(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    r = await post(client_for, app, t, [item(last_activity_at="2026-11-12T09:00:00")])
    assert r.status_code == 422


async def test_ingest_rejects_over_100_items(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    many = [item(external_id=f"i{n}") for n in range(101)]
    assert (await post(client_for, app, t, many)).status_code == 422
    assert (await post(client_for, app, t, many[:100])).status_code == 200


async def test_open_item_without_waiting_on_is_422(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    assert (await post(client_for, app, t, [item(waiting_on=None)])).status_code == 422


async def test_done_item_may_send_null_waiting_on(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    r = await post(client_for, app, t, [item(status_category="done", waiting_on=None)])
    assert r.status_code == 200


async def test_waiting_on_needs_prefix_is_422(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    assert (await post(client_for, app, t, [item(waiting_on="owner")])).status_code == 422


async def test_unknown_field_is_422(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    assert (await post(client_for, app, t, [item(body="secret")])).status_code == 422


async def test_token_bound_to_other_source_is_403(make_app, client_for):
    app, repo, t = await setup(make_app, client_for, source="github")
    assert (await post(client_for, app, t, [item()], source="kanban")).status_code == 403
    assert (await post(client_for, app, t, [item()], source="github")).status_code == 200


async def test_read_scope_token_cannot_ingest(make_app, client_for):
    app, repo = make_app(clock=lambda: NOW)
    t = await add_token(repo, name="r", scopes="read")
    assert (await post(client_for, app, t, [item()])).status_code == 403


async def test_event_payload_has_changed_fields_only(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    await post(client_for, app, t, [item()])
    await post(client_for, app, t, [item(title="New")])
    ev = (await events(repo))[-1]
    assert ev["kind"] == "item.updated"
    assert set(json.loads(ev["payload"])) == {"title"}


async def test_project_key_does_not_move_epic_filed_item_out_of_epic_project(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    await mk_epic(repo)
    await repo.execute("insert into projects(key,name,created_at) values ('OTHER','o',1)")
    await post(client_for, app, t, [item(epic_key="DEMO-E1")])
    before = (await row(repo))["project_id"]
    await post(client_for, app, t, [item(last_activity_at=T2, project_key="OTHER")])
    assert (await row(repo))["project_id"] == before


class CountingD1:
    """Wraps FakeD1 and counts D1 round trips (each statement run or batch is one call)."""

    def __init__(self, db):
        self._db, self.calls = db, 0
        orig_run, orig_batch = db._run_one, db.batch

        def run_one(stmt):
            self.calls += 1
            return orig_run(stmt)

        async def batch(stmts):
            self.calls += 1
            return await orig_batch(stmts)

        db._run_one, db.batch = run_one, batch


async def test_100_item_ingest_uses_bounded_d1_calls(client_for):
    from loopboard.app import build_app
    from loopboard.db import Repo
    from tests.fakes.d1 import FakeD1

    db = FakeD1()
    db.apply_migrations()
    repo = Repo(db)
    app = build_app(db=db, clock=lambda: NOW)
    t = await add_token(repo, name="bot", scopes="ingest", source="kanban")
    await mk_epic(repo)
    await mk_epic(repo, "DEMO-E2")
    items = [item(external_id=f"i{n}", project_key="DEMO",
                  **({"epic_key": f"DEMO-E{1 + n % 2}"} if n % 3 == 0 else {}))
             for n in range(100)]
    counter = CountingD1(db)

    r = await post(client_for, app, t, items)
    assert r.status_code == 200 and r.json()["created"] == 100
    assert counter.calls <= 10, counter.calls
    assert len(await events(repo)) == 100
    assert r.json()["auto_tasks"] == 34

    counter.calls = 0
    r = await post(client_for, app, t, items)
    assert (r.json()["created"], r.json()["updated"]) == (0, 0)
    assert counter.calls <= 10, counter.calls

    counter.calls = 0
    r = await post(client_for, app, t, [dict(x, title="new", last_activity_at=T2) for x in items])
    assert r.json()["updated"] == 100
    assert counter.calls <= 10, counter.calls
    e1 = await repo.first("select board_column from epics where key='DEMO-E1'")
    assert e1["board_column"] == "todo"


async def test_duplicate_new_item_in_batch_creates_then_updates(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    r = await post(client_for, app, t, [item(), item(title="B", last_activity_at=T2)])
    assert (r.json()["created"], r.json()["updated"]) == (1, 1)
    assert (await row(repo))["title"] == "B"
    assert [e["kind"] for e in await events(repo)] == ["item.created", "item.updated"]


async def test_ingest_recomputes_epic_column(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    await mk_epic(repo)
    await post(client_for, app, t, [item(epic_key="DEMO-E1", status_category="in_progress")])
    assert (await repo.first("select board_column from epics"))["board_column"] == "in_progress"


async def test_project_key_does_not_move_standalone_item(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    await repo.execute("insert into projects(key,name,created_at) values ('DEMO','d',1)")
    await repo.execute("insert into projects(key,name,created_at) values ('OTHER','o',1)")
    await post(client_for, app, t, [item(project_key="DEMO")])
    await repo.execute("update items set filing='standalone'")
    before = (await row(repo))["project_id"]
    await post(client_for, app, t, [item(last_activity_at=T2, project_key="OTHER")])
    assert (await row(repo))["project_id"] == before


async def test_out_of_range_timestamp_in_ingest_is_422(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    r = await post(client_for, app, t, [item(last_activity_at="9999-12-31T23:59:59-14:00")])
    assert r.status_code == 422


async def test_overlapping_update_never_regresses_and_writes_no_event(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    await post(client_for, app, t, [item(title="A")])
    n_events = len(await events(repo))
    newer = parse_ts("2026-11-12T12:00:00+07:00")
    app_repo = app.state.repo
    orig = app_repo.batch

    async def racing_batch(stmts):
        # another writer advances the row between our read and our write
        await repo.execute("update items set title='WINNER', last_activity_at=? where external_id='a'", (newer,))
        return await orig(stmts)

    app_repo.batch = racing_batch
    r = await post(client_for, app, t, [item(title="LOSER", last_activity_at=T2)])
    app_repo.batch = orig
    assert r.status_code == 200
    assert r.json()["skipped_older"] == 1 and r.json()["updated"] == 0
    got = await row(repo)
    assert got["title"] == "WINNER" and got["last_activity_at"] == newer
    assert len(await events(repo)) == n_events


async def test_far_future_timestamps_reject_whole_request(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    ok = "2026-11-12T09:00:00Z"
    from datetime import datetime, timezone

    def iso(sec):
        return datetime.fromtimestamp(sec, timezone.utc).isoformat()

    for field in ("last_activity_at", "merged_at", "live_at"):
        over = {"last_activity_at": ok, field: iso(NOW + 3601)}
        r = await post(client_for, app, t, [item(external_id="good", last_activity_at=ok), item(external_id="bad", **over)])
        assert r.status_code == 422, field
        assert await row(repo, "good") is None and await row(repo, "bad") is None
    edge = await post(client_for, app, t, [item(last_activity_at=iso(NOW + 3600))])
    assert edge.status_code == 200


async def test_concurrent_create_retries_as_update(make_app, client_for):
    """Another writer creates the same (source, external_id) between our read and our batch: the
    UNIQUE violation retries the request once, so the item is updated instead of a 500."""
    app, repo, t = await setup(make_app, client_for)
    orig = repo.batch
    calls = []

    async def racing_batch(stmts):
        calls.append(len(stmts))
        if len(calls) == 1:
            await repo.execute(
                "insert into items(source, external_id, title, status_category, waiting_on, filing,"
                " last_activity_at, created_at, updated_at) values"
                " ('kanban', 'a', 'Other', 'todo', 'agent:hermes', 'unfiled', ?, 1, 1)",
                (parse_ts(T1),))
        return await orig(stmts)

    app.state.repo.batch = racing_batch
    r = await post(client_for, app, t, [item(title="Mine", last_activity_at=T2)])
    assert r.status_code == 200, r.text
    assert (r.json()["created"], r.json()["updated"]) == (0, 1)
    assert len(calls) == 2
    assert (await row(repo))["title"] == "Mine"
    assert [e["kind"] for e in await events(repo)] == ["item.updated"]


async def test_unbound_ingest_token_is_403(make_app, client_for):
    app, repo, t = await setup(make_app, client_for, source=None)
    r = await post(client_for, app, t, [item()])
    assert r.status_code == 403
    assert r.json()["detail"] == "connector tokens must be bound to a source"
    assert await row(repo) is None


# v1a.4: filing by [EPIC-KEY] title tag (the connector sends it as epic_key)


async def test_tag_files_new_item(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    eid = await mk_epic(repo, "DEMO-E5")
    r = await post(client_for, app, t, [item(epic_key="DEMO-E5")])
    assert r.status_code == 200 and r.json()["created"] == 1 and r.json()["unknown_epic"] == 0
    x = await row(repo)
    pid = (await repo.first("select project_id from epics where id=?", (eid,)))["project_id"]
    assert (x["filing"], x["epic_id"], x["project_id"]) == ("epic", eid, pid)


async def test_tag_files_unfiled_item(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    eid = await mk_epic(repo, "DEMO-E5")
    await post(client_for, app, t, [item()])
    assert (await row(repo))["filing"] == "unfiled"
    r = await post(client_for, app, t, [item(epic_key="DEMO-E5", last_activity_at=T2)])
    assert r.json()["updated"] == 1
    x = await row(repo)
    assert (x["filing"], x["epic_id"]) == ("epic", eid)


async def test_tag_never_overrides_existing_filing(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    e1 = await mk_epic(repo, "DEMO-E1")
    await mk_epic(repo, "DEMO-E5")
    await repo.execute("insert into projects(key,name,created_at) values ('OTHER','o',1)")
    other = (await repo.first("select id from projects where key='OTHER'"))["id"]
    await post(client_for, app, t, [item(external_id=x, project_key="OTHER") for x in ("e", "s", "i")])
    await repo.execute("update items set filing='epic', epic_id=?, project_id=(select project_id from epics where id=?)"
                       " where external_id='e'", (e1, e1))
    await repo.execute("update items set filing='standalone' where external_id='s'")
    await repo.execute("update items set filing='ignored' where external_id='i'")
    before = {x: dict(await row(repo, x)) for x in ("e", "s", "i")}
    r = await post(client_for, app, t, [item(external_id=x, epic_key="DEMO-E5", title="New", last_activity_at=T2)
                                        for x in ("e", "s", "i")])
    assert r.status_code == 200 and r.json()["updated"] == 3
    for x in ("e", "s", "i"):
        after = await row(repo, x)
        assert (after["filing"], after["epic_id"], after["project_id"]) == \
            (before[x]["filing"], before[x]["epic_id"], before[x]["project_id"]), x
        assert after["title"] == "New"
    assert before["s"]["project_id"] == other
    assert not [e for e in await events(repo) if e["kind"] == "item.filed"]
    # nor does a task key or a ref, and no auto-task is made
    await mk_task(repo, "DEMO", key="DEMO-1", refs='["OPS-8001"]')
    n_tasks = (await repo.first("select count(*) as n from tasks"))["n"]
    r = await post(client_for, app, t, [item(external_id=x, task_key="DEMO-1", title="fix(OPS-8001): y",
                                             last_activity_at="2026-11-12T11:00:00+07:00") for x in ("e", "s", "i")])
    assert r.json()["updated"] == 3
    for x in ("e", "s", "i"):
        after = await row(repo, x)
        assert (after["filing"], after["epic_id"], after["task_id"]) == \
            (before[x]["filing"], before[x]["epic_id"], before[x]["task_id"]), x
    assert (await repo.first("select count(*) as n from tasks"))["n"] == n_tasks
    assert r.json()["linked_task"] == 0 and r.json()["auto_tasks"] == 0


async def test_unknown_epic_key_does_not_fail_chunk(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    eid = await mk_epic(repo, "DEMO-E5")
    await post(client_for, app, t, [item(external_id="old")])
    r = await post(client_for, app, t, [
        item(external_id="ok"), item(external_id="new", epic_key="DEMO-E9"),
        item(external_id="old", epic_key="DEMO-E9", title="Renamed", last_activity_at=T2),
        item(external_id="tagged", epic_key="DEMO-E5")])
    assert r.status_code == 200
    assert {k: r.json()[k] for k in ("created", "updated", "unknown_epic")} == \
        {"created": 3, "updated": 1, "unknown_epic": 2}
    assert (await row(repo, "ok"))["filing"] == "unfiled"
    assert ((await row(repo, "new"))["filing"], (await row(repo, "new"))["epic_id"]) == ("unfiled", None)
    old = await row(repo, "old")
    assert (old["filing"], old["title"]) == ("unfiled", "Renamed")
    assert ((await row(repo, "tagged"))["filing"], (await row(repo, "tagged"))["epic_id"]) == ("epic", eid)


async def test_canceled_epic_counts_as_unknown(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    await mk_epic(repo, "DEMO-E5")
    await repo.execute("update epics set manual_column='canceled' where key='DEMO-E5'")
    r = await post(client_for, app, t, [item(epic_key="DEMO-E5")])
    assert r.status_code == 200 and r.json()["unknown_epic"] == 1
    x = await row(repo)
    assert (x["filing"], x["epic_id"]) == ("unfiled", None)


async def test_ingest_response_has_unknown_epic_zero_by_default(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    r = await post(client_for, app, t, [item()])
    assert r.json()["unknown_epic"] == 0


async def test_tag_filing_emits_event_and_recomputes(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    eid = await mk_epic(repo, "DEMO-E5")
    await post(client_for, app, t, [item(status_category="in_progress")])
    r = await post(client_for, app, t, [item(epic_key="DEMO-E5", status_category="in_progress",
                                             last_activity_at=T2)])
    assert r.json()["updated"] == 1
    filed = [e for e in await events(repo) if e["kind"] == "item.filed"]
    assert len(filed) == 1
    (e,) = filed
    assert (e["actor"], e["via"]) == ("bot", "ingest")
    payload = json.loads(e["payload"])
    assert (payload["filing"], payload["epic_id"]) == ("epic", eid)
    assert (await repo.first("select board_column from epics where id=?", (eid,)))["board_column"] == "in_progress"
    col = await repo.query("select * from events where subject_type='epic' and kind='epic.column_changed'")
    assert len(col) == 1

    # A new item filed by its tag: item.created carries the filing; the epic is recomputed too.
    e2 = await mk_epic(repo, "DEMO-E6")
    await post(client_for, app, t, [item(external_id="b", epic_key="DEMO-E6", status_category="review",
                                         waiting_on="human:owner")])
    created = json.loads((await events(repo))[-1]["payload"])
    assert (created["filing"], created["epic_id"]) == ("epic", e2)
    assert (await repo.first("select board_column from epics where id=?", (e2,)))["board_column"] == "review"


# --- tasks ---

async def mk_task(repo, pkey="DEMO", key=None, epic_key=None, status="todo", refs="[]", merged_into=None):
    p = await repo.first("select id from projects where key=?", (pkey,))
    pid = p["id"] if p else await repo.execute("insert into projects(key,name,created_at) values (?,?,1)", (pkey, pkey))
    seq = int(key.split("-")[1])
    eid = (await repo.first("select id from epics where key=?", (epic_key,)))["id"] if epic_key else None
    return await repo.execute(
        "insert into tasks(project_id,epic_id,seq,key,summary,description,done_when,status,owner,waiting_on,"
        "reporter,refs,merged_into,last_activity_at,created_at,updated_at)"
        " values(?,?,?,?,'s','d','w',?,'o','agent:a','tester',?,?,1,1,1)",
        (pid, eid, seq, key, status, refs, merged_into))


async def test_task_prefix_links_new_item(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    eid = await mk_epic(repo, "DEMO-E1")
    tid = await mk_task(repo, key="DEMO-12", epic_key="DEMO-E1")
    r = await post(client_for, app, t, [item(task_key="DEMO-12", status_category="in_progress")])
    assert (r.json()["linked_task"], r.json()["unknown_task"], r.json()["auto_tasks"]) == (1, 0, 0)
    x = await row(repo)
    assert (x["task_id"], x["epic_id"], x["filing"]) == (tid, eid, "epic")
    assert (await repo.first("select board_column from epics where id=?", (eid,)))["board_column"] == "in_progress"
    created = json.loads((await events(repo))[0]["payload"])
    assert created["task_key"] == "DEMO-12"
    # a task with no epic: standalone; an unfiled item is linked on a later sync too
    await mk_task(repo, key="DEMO-13")
    await post(client_for, app, t, [item(external_id="b")])
    await post(client_for, app, t, [item(external_id="b", task_key="DEMO-13", last_activity_at=T2)])
    b = await row(repo, "b")
    assert (b["filing"], b["epic_id"], b["project_id"]) == ("standalone", None, 1)
    filed = [json.loads(e["payload"]) for e in await events(repo) if e["kind"] == "item.filed"]
    assert filed[-1]["task_key"] == "DEMO-13"


async def test_task_prefix_of_merged_task_links_survivor(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    a = await mk_task(repo, key="DEMO-1")
    b = await mk_task(repo, key="DEMO-2", status="canceled", merged_into=a)
    await mk_task(repo, key="DEMO-3", status="canceled", merged_into=b)
    r = await post(client_for, app, t, [item(task_key="DEMO-3"), item(external_id="c", task_key="DEMO-4")])
    assert (r.json()["linked_task"], r.json()["unknown_task"]) == (1, 1)
    assert (await row(repo))["task_id"] == a
    assert (await row(repo, "c"))["filing"] == "unfiled"


async def test_ref_matches_whole_token_in_same_project_only(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    await mk_epic(repo, "SAMPLE-E1", pkey="SAMPLE")
    hit = await mk_task(repo, key="DEMO-1", refs='["OPS-8001"]')
    await mk_task(repo, key="DEMO-2", refs='["OPS-80"]')
    await mk_task(repo, key="DEMO-3", refs='["OPS-77"]', status="canceled")
    await mk_task(repo, "SAMPLE", key="SAMPLE-1", refs='["OPS-9"]')
    r = await post(client_for, app, t, [
        item(external_id="a", title="fix(OPS-8001): retry", project_key="DEMO"),
        item(external_id="b", title="OPS-80011 and XOPS-80 are not refs", project_key="DEMO"),
        item(external_id="f", title="OPS-80-retry is not a ref either", project_key="DEMO"),
        item(external_id="c", title="OPS-9 is SAMPLE's ref", project_key="DEMO"),
        item(external_id="d", title="OPS-77 belongs to a canceled task", project_key="DEMO"),
        item(external_id="e", title="OPS-8001 without a project")])
    assert r.json()["linked_task"] == 1
    assert (await row(repo, "a"))["task_id"] == hit and (await row(repo, "a"))["filing"] == "standalone"
    for x in "bcdef":
        assert (await row(repo, x))["filing"] == "unfiled", x


async def test_epic_prefix_creates_auto_task_and_links(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    eid = await mk_epic(repo, "DEMO-E5")
    await mk_task(repo, key="DEMO-1")
    r = await post(client_for, app, t, [item(epic_key="DEMO-E5", title="Add retry", url="https://example.test/pr/1",
                                             owner="coder", status_category="review", waiting_on="human:owner")])
    assert r.json()["auto_tasks"] == 1
    task = await repo.first("select * from tasks where key='DEMO-2'")
    x = await row(repo)
    assert (task["epic_id"], task["summary"], task["description"], task["done_when"], task["owner"],
            task["reporter"], task["waiting_on"], task["status"]) == (
        eid, "Add retry", "Created from https://example.test/pr/1", "The linked work is live.", "coder", "bot",
        "human:owner", "todo")
    assert task["origin_item_id"] == x["id"]
    assert (x["task_id"], x["epic_id"], x["filing"]) == (task["id"], eid, "epic")
    ev = await repo.first("select * from events where kind='task.created'")
    assert (ev["subject_id"], ev["actor"], ev["via"]) == (task["id"], "bot", "ingest")
    # without an owner the task's owner is the source; the description falls back to source:external_id
    await post(client_for, app, t, [item(external_id="n", epic_key="DEMO-E5")])
    t3 = await repo.first("select * from tasks where key='DEMO-3'")
    assert (t3["owner"], t3["description"]) == ("kanban", "Created from kanban:n")


async def test_two_items_same_epic_tag_get_two_tasks_in_one_batch(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    await mk_epic(repo, "DEMO-E1")
    await mk_epic(repo, "SAMPLE-E1", pkey="SAMPLE")
    await mk_task(repo, key="DEMO-4")
    r = await post(client_for, app, t, [item(external_id="a", epic_key="DEMO-E1"),
                                        item(external_id="b", epic_key="DEMO-E1"),
                                        item(external_id="c", epic_key="SAMPLE-E1"),
                                        item(external_id="a", epic_key="DEMO-E1", title="again", last_activity_at=T2)])
    assert r.json()["auto_tasks"] == 3
    keys = {x: (await repo.first("select t.key from tasks t join items i on i.task_id=t.id where i.external_id=?",
                                 (x,)))["key"] for x in "abc"}
    assert keys == {"a": "DEMO-5", "b": "DEMO-6", "c": "SAMPLE-1"}


async def test_lost_task_seq_race_retries(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    await mk_epic(repo, "DEMO-E1")
    db = app.state.repo.db
    orig = db.batch
    calls = {"n": 0}

    async def racing(stmts):
        calls["n"] += 1
        if calls["n"] == 1:  # someone else takes DEMO-1 just before our batch
            await mk_task(repo, key="DEMO-1")
        return await orig(stmts)

    db.batch = racing
    r = await post(client_for, app, t, [item(epic_key="DEMO-E1")])
    assert r.status_code == 200 and r.json()["auto_tasks"] == 1
    assert (await repo.first("select t.key from tasks t join items i on i.task_id=t.id"))["key"] == "DEMO-2"


async def test_unknown_task_key_does_not_fail_chunk(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    await mk_task(repo, key="DEMO-1", status="canceled")
    r = await post(client_for, app, t, [item(external_id="a", task_key="DEMO-9"), item(external_id="b", task_key="DEMO-1"),
                                        item(external_id="c")])
    assert r.status_code == 200 and r.json()["created"] == 3
    assert (r.json()["unknown_task"], r.json()["linked_task"]) == (2, 0)
    assert {(await row(repo, x))["filing"] for x in "abc"} == {"unfiled"}


async def test_ingest_d1_calls_bounded(client_for):
    """Base (before tasks) used 8 / 5 / 8 D1 calls for these three posts; tasks add at most 3."""
    from loopboard.app import build_app
    from loopboard.db import Repo
    from tests.fakes.d1 import FakeD1

    db = FakeD1()
    db.apply_migrations()
    repo = Repo(db)
    app = build_app(db=db, clock=lambda: NOW)
    t = await add_token(repo, name="bot", scopes="ingest", source="kanban")
    await mk_epic(repo)
    await mk_epic(repo, "DEMO-E2")
    await mk_task(repo, key="DEMO-1", refs='["OPS-1"]')
    items = [item(external_id=f"i{n}", project_key="DEMO", title=f"t {n}",
                  **({"epic_key": f"DEMO-E{1 + n % 2}"} if n % 3 == 0 else
                     {"task_key": "DEMO-1"} if n % 3 == 1 else {}))
             for n in range(100)]
    counter = CountingD1(db)
    r = await post(client_for, app, t, items)
    assert (r.json()["auto_tasks"], r.json()["linked_task"]) == (34, 33)
    assert counter.calls <= 8 + 3, counter.calls
    counter.calls = 0
    await post(client_for, app, t, items)
    assert counter.calls <= 5 + 3, counter.calls
    counter.calls = 0
    await post(client_for, app, t, [dict(x, title="new", last_activity_at=T2) for x in items])
    assert counter.calls <= 8 + 3, counter.calls


async def test_ingest_merged_keys_d1_calls_bounded(client_for):
    """50 items tagged with 50 merged-away keys (chains of 2) cost at most MERGE_DEPTH more D1 calls
    than 50 items tagged with live keys, and each links to its survivor."""
    from loopboard.app import build_app
    from loopboard.db import Repo
    from loopboard.ingest import MERGE_DEPTH
    from tests.fakes.d1 import FakeD1

    db = FakeD1()
    db.apply_migrations()
    repo = Repo(db)
    app = build_app(db=db, clock=lambda: NOW)
    t = await add_token(repo, name="bot", scopes="ingest", source="kanban")
    survivors = {}
    for n in range(1, 51):
        survivors[n] = await mk_task(repo, key=f"DEMO-{n}")
        mid = await mk_task(repo, key=f"DEMO-{50 + n}", status="canceled", merged_into=survivors[n])
        await mk_task(repo, key=f"DEMO-{100 + n}", status="canceled", merged_into=mid)
    counter = CountingD1(db)
    r = await post(client_for, app, t, [item(external_id=f"live{n}", task_key=f"DEMO-{n}") for n in range(1, 51)])
    assert r.json()["linked_task"] == 50
    base, counter.calls = counter.calls, 0
    r = await post(client_for, app, t, [item(external_id=f"m{n}", task_key=f"DEMO-{100 + n}") for n in range(1, 51)])
    assert r.json()["linked_task"] == 50
    assert counter.calls <= base + MERGE_DEPTH, (base, counter.calls)
    for n in range(1, 51):
        assert (await row(repo, f"m{n}"))["task_id"] == survivors[n]


async def test_auto_task_from_item_without_waiting_on_waits_on_source(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    await mk_epic(repo, "DEMO-E5")
    r = await post(client_for, app, t, [item(epic_key="DEMO-E5", status_category="done", waiting_on=None)])
    assert r.json()["auto_tasks"] == 1
    task = await repo.first("select waiting_on from tasks where key='DEMO-1'")
    assert task["waiting_on"] == "source:kanban"
