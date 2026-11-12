import json

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


async def test_unknown_epic_key_is_422(make_app, client_for):
    app, repo, t = await setup(make_app, client_for)
    r = await post(client_for, app, t, [item(external_id="ok"), item(epic_key="DEMO-E9")])
    assert r.status_code == 422
    assert await row(repo, "ok") is None


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
