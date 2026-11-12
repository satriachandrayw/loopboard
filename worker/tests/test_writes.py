import json

from tests.test_auth import add_token, bearer

NOW = 1_800_000_000


async def setup(make_app):
    app, repo = make_app(clock=lambda: NOW)
    t = await add_token(repo, name="owner-tok", scopes="write")
    return app, repo, bearer(t)


async def req(client_for, app, h, method, path, body=None):
    async with client_for(app) as c:
        return await c.request(method, path, json=body, headers=h)


async def mk_project(client_for, app, h, key="DEMO"):
    return await req(client_for, app, h, "POST", "/api/projects", {"key": key, "name": key})


async def mk_epic(client_for, app, h, title="E", project="DEMO", **kw):
    return await req(client_for, app, h, "POST", f"/api/projects/{project}/epics", {"title": title, **kw})


async def seeded(make_app, client_for):
    app, repo, h = await setup(make_app)
    await mk_project(client_for, app, h)
    await mk_epic(client_for, app, h)
    return app, repo, h


async def add_item(repo, ext="1", cat="review", filing="unfiled", epic_id=None, project_id=None,
                   merged=None, live=None):
    return await repo.execute(
        "insert into items(source,external_id,project_id,epic_id,filing,title,status_category,merged_at,"
        "live_at,last_activity_at,created_at,updated_at) values('kanban',?,?,?,?,'t',?,?,?,1,1,1)",
        (ext, project_id, epic_id, filing, cat, merged, live))


async def epic(repo, key="DEMO-E1"):
    return await repo.first("select * from epics where key=?", (key,))


async def evs(repo, kind=None):
    rows = await repo.query("select * from events order by id")
    return [r for r in rows if kind is None or r["kind"] == kind]


async def test_create_epic_assigns_sequential_keys(make_app, client_for):
    app, repo, h = await setup(make_app)
    r = await mk_project(client_for, app, h)
    assert r.status_code == 201
    r1 = await mk_epic(client_for, app, h)
    r2 = await mk_epic(client_for, app, h, title="E2")
    assert (r1.status_code, r1.json()["key"], r2.json()["key"]) == (201, "DEMO-E1", "DEMO-E2")


async def test_create_epic_defaults_manual_backlog_stage_idea(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    e = await epic(repo)
    assert (e["manual_column"], e["board_column"], e["stage"], e["last_activity_at"]) == (
        "backlog", "backlog", "idea", NOW)


async def test_duplicate_project_is_409_and_unknown_project_404(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    assert (await mk_project(client_for, app, h)).status_code == 409
    assert (await mk_epic(client_for, app, h, project="NOPE")).status_code == 404


async def test_patch_epic_rejects_derived_column(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    r = await req(client_for, app, h, "PATCH", "/api/epics/DEMO-E1", {"manual_column": "in_progress"})
    assert r.status_code == 422


async def test_patch_epic_empty_body_is_422(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    assert (await req(client_for, app, h, "PATCH", "/api/epics/DEMO-E1", {})).status_code == 422


async def test_patch_unknown_epic_is_404(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    assert (await req(client_for, app, h, "PATCH", "/api/epics/DEMO-E9", {"stage": "spec"})).status_code == 404


async def test_patch_event_payload_has_changed_fields_only(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    r = await req(client_for, app, h, "PATCH", "/api/epics/DEMO-E1", {"stage": "spec"})
    assert r.status_code == 200 and r.json()["stage"] == "spec"
    (e,) = await evs(repo, "epic.updated")
    assert set(json.loads(e["payload"])) == {"stage"}


async def test_every_write_records_actor_and_via(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    eid = (await epic(repo))["id"]
    a = await add_item(repo, "1", epic_id=eid, filing="epic", merged=1)
    b = await add_item(repo, "2")
    await req(client_for, app, h, "PATCH", "/api/epics/DEMO-E1", {"stage": "spec"})
    await req(client_for, app, h, "POST", "/api/epics/DEMO-E1/confirm-done")
    await req(client_for, app, h, "POST", f"/api/items/{b}/filing", {"filing": "ignored"})
    await req(client_for, app, h, "POST", f"/api/items/{a}/deployed", {"live_at": "2026-11-12T09:00:00Z"})
    r = await req(client_for, app, h, "POST", "/api/relations",
                  {"from_type": "item", "from_id": a, "to_type": "item", "to_id": b})
    await req(client_for, app, h, "DELETE", f"/api/relations/{r.json()['id']}")
    await req(client_for, app, h, "PUT", "/api/sources/kanban", {"stall_hours": 12})
    rows = await evs(repo)
    kinds = {e["kind"] for e in rows}
    assert {"project.created", "epic.created", "epic.updated", "epic.confirmed_done", "item.filed",
            "item.deployed", "relation.created", "relation.deleted", "source.updated"} <= kinds
    for e in rows:
        if e["kind"] != "epic.column_changed":
            assert (e["actor"], e["via"]) == ("owner-tok", "api"), e["kind"]


async def test_patch_recomputes_board_column(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    r = await req(client_for, app, h, "PATCH", "/api/epics/DEMO-E1", {"manual_column": "todo"})
    assert r.json()["board_column"] == "todo"
    assert (await epic(repo))["board_column"] == "todo"


async def test_confirm_done_moves_code_less_epic_to_done(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    eid = (await epic(repo))["id"]
    await add_item(repo, "1", cat="done", epic_id=eid, filing="epic")
    await req(client_for, app, h, "PATCH", "/api/epics/DEMO-E1", {"manual_column": "todo"})
    assert (await epic(repo))["board_column"] == "review"
    r = await req(client_for, app, h, "POST", "/api/epics/DEMO-E1/confirm-done")
    assert r.status_code == 200
    e = await epic(repo)
    assert (e["board_column"], e["done_confirmed_at"]) == ("done", NOW)


async def test_filing_moves_item_and_recomputes_both_epics(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    await mk_epic(client_for, app, h, title="E2", manual_column="todo")
    e1, e2 = (await epic(repo))["id"], (await epic(repo, "DEMO-E2"))["id"]
    i = await add_item(repo, "1", cat="in_progress", epic_id=e1, filing="epic")
    await req(client_for, app, h, "PATCH", "/api/epics/DEMO-E1", {"manual_column": "todo"})
    assert (await epic(repo))["board_column"] == "in_progress"
    r = await req(client_for, app, h, "POST", f"/api/items/{i}/filing", {"filing": "epic", "epic_key": "DEMO-E2"})
    assert r.status_code == 200
    assert (await epic(repo))["board_column"] == "todo"
    assert (await epic(repo, "DEMO-E2"))["board_column"] == "in_progress"
    it = await repo.first("select * from items where id=?", (i,))
    assert (it["epic_id"], it["filing"]) == (e2, "epic")


async def test_filing_standalone_needs_project_else_422(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    i = await add_item(repo, "1")
    r = await req(client_for, app, h, "POST", f"/api/items/{i}/filing", {"filing": "standalone"})
    assert r.status_code == 422
    r = await req(client_for, app, h, "POST", f"/api/items/{i}/filing",
                  {"filing": "standalone", "project_key": "DEMO"})
    assert r.status_code == 200
    it = await repo.first("select * from items where id=?", (i,))
    assert (it["filing"], it["epic_id"], it["project_id"]) == ("standalone", None, 1)


async def test_filing_epic_requires_epic_key_and_unknown_is_404(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    i = await add_item(repo, "1")
    assert (await req(client_for, app, h, "POST", f"/api/items/{i}/filing", {"filing": "epic"})).status_code == 422
    r = await req(client_for, app, h, "POST", f"/api/items/{i}/filing", {"filing": "epic", "epic_key": "DEMO-E9"})
    assert r.status_code == 404
    assert (await req(client_for, app, h, "POST", "/api/items/999/filing", {"filing": "ignored"})).status_code == 404


async def test_filing_ignored_removes_item_from_derivation(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    eid = (await epic(repo))["id"]
    i = await add_item(repo, "1", cat="in_progress", epic_id=eid, filing="epic")
    await req(client_for, app, h, "PATCH", "/api/epics/DEMO-E1", {"manual_column": "todo"})
    assert (await epic(repo))["board_column"] == "in_progress"
    r = await req(client_for, app, h, "POST", f"/api/items/{i}/filing", {"filing": "ignored"})
    assert r.status_code == 200
    assert (await epic(repo))["board_column"] == "todo"
    assert (await repo.first("select epic_id from items where id=?", (i,)))["epic_id"] is None


async def test_deployed_requires_merged_pr(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    i = await add_item(repo, "1")
    r = await req(client_for, app, h, "POST", f"/api/items/{i}/deployed", {"live_at": "2026-11-12T09:00:00Z"})
    assert r.status_code == 422
    r = await req(client_for, app, h, "POST", f"/api/items/{i}/deployed", {"live_at": "2026-11-12T09:00:00"})
    assert r.status_code == 422


async def test_deployed_moves_epic_to_done_when_all_done(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    eid = (await epic(repo))["id"]
    i = await add_item(repo, "1", cat="review", epic_id=eid, filing="epic", merged=5)
    await req(client_for, app, h, "PATCH", "/api/epics/DEMO-E1", {"manual_column": "todo"})
    assert (await epic(repo))["board_column"] == "review"
    r = await req(client_for, app, h, "POST", f"/api/items/{i}/deployed", {"live_at": "2026-11-12T09:00:00+07:00"})
    assert r.status_code == 200
    assert (await repo.first("select live_at from items where id=?", (i,)))["live_at"] == 1_794_448_800
    assert (await epic(repo))["board_column"] == "done"


async def rel(a, b, **kw):
    return {"from_type": "item", "from_id": a, "to_type": "item", "to_id": b, **kw}


async def test_relation_requires_existing_endpoints(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    a = await add_item(repo, "1")
    r = await req(client_for, app, h, "POST", "/api/relations", await rel(a, 999))
    assert r.status_code == 404


async def test_relation_self_is_422(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    a = await add_item(repo, "1")
    assert (await req(client_for, app, h, "POST", "/api/relations", await rel(a, a))).status_code == 422


async def test_relation_duplicate_is_409(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    a, b = await add_item(repo, "1"), await add_item(repo, "2")
    assert (await req(client_for, app, h, "POST", "/api/relations", await rel(a, b))).status_code == 201
    assert (await req(client_for, app, h, "POST", "/api/relations", await rel(a, b))).status_code == 409


async def test_delete_relation_removes_row_and_logs_event(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    a, b = await add_item(repo, "1"), await add_item(repo, "2")
    rid = (await req(client_for, app, h, "POST", "/api/relations", await rel(a, b))).json()["id"]
    assert (await req(client_for, app, h, "DELETE", f"/api/relations/{rid}")).status_code == 204
    assert await repo.query("select * from relations") == []
    assert len(await evs(repo, "relation.deleted")) == 1
    assert (await req(client_for, app, h, "DELETE", f"/api/relations/{rid}")).status_code == 404


async def test_put_source_rejects_zero_hours(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    assert (await req(client_for, app, h, "PUT", "/api/sources/kanban", {"stall_hours": 0})).status_code == 422
    r = await req(client_for, app, h, "PUT", "/api/sources/kanban", {"stall_hours": 6})
    assert r.status_code == 200
    r = await req(client_for, app, h, "PUT", "/api/sources/kanban", {"stall_hours": 8})
    assert (await repo.first("select stall_hours from sources where name='kanban'"))["stall_hours"] == 8


async def test_read_scope_cannot_write(make_app, client_for):
    app, repo, _ = await setup(make_app)
    t = await add_token(repo, name="ro", scopes="read")
    assert (await mk_project(client_for, app, bearer(t))).status_code == 403
