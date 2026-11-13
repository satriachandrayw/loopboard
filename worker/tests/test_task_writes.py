import json
import subprocess
import sys
from pathlib import Path

from tests.test_auth import add_token, bearer
from tests.test_writes import NOW, add_item, mk_epic, mk_project, req, setup

TASK = {"summary": "Ship it", "description": "What it is.", "done_when": "It is live.", "owner": "coder",
        "waiting_on": "agent:coder"}


async def world(make_app, client_for):
    """DEMO with DEMO-E1, SAMPLE with SAMPLE-E1; an agent write token and a human write token."""
    app, repo, h = await setup(make_app)
    await repo.execute("update api_tokens set scopes = 'read,write' where name = 'owner-tok'")
    for p in ("DEMO", "SAMPLE"):
        await mk_project(client_for, app, h, p)
        await mk_epic(client_for, app, h, project=p)
    hh = bearer(await add_token(repo, name="person", scopes="read,write,human"))
    return app, repo, h, hh


async def mk_task(client_for, app, h, project="DEMO", **kw):
    return await req(client_for, app, h, "POST", f"/api/projects/{project}/tasks", {**TASK, **kw})


async def task_row(repo, key):
    return await repo.first("select * from tasks where key=?", (key,))


async def invariant(repo):
    """Every filed item has a task; its epic and filing follow the task."""
    rows = await repo.query("select i.*, t.epic_id as t_epic, t.project_id as t_project from items i "
                            "left join tasks t on t.id = i.task_id")
    for i in rows:
        if i["filing"] in ("epic", "standalone"):
            assert i["task_id"] is not None, i
            assert i["epic_id"] == i["t_epic"] and i["project_id"] == i["t_project"], i
            assert i["filing"] == ("epic" if i["t_epic"] else "standalone"), i
        else:
            assert i["task_id"] is None and i["epic_id"] is None, i


async def kinds(repo, stype=None):
    sql = "select kind from events" + (" where subject_type=?" if stype else "") + " order by id"
    return [r["kind"] for r in await repo.query(sql, (stype,) if stype else ())]


async def test_create_task_keys_per_project(make_app, client_for):
    app, repo, h, _ = await world(make_app, client_for)
    r1 = await mk_task(client_for, app, h, epic_key="DEMO-E1")
    r2 = await mk_task(client_for, app, h)
    r3 = await mk_task(client_for, app, h, project="SAMPLE")
    assert (r1.status_code, r1.json()["key"], r2.json()["key"], r3.json()["key"]) == (
        201, "DEMO-1", "DEMO-2", "SAMPLE-1")
    v = r1.json()
    assert (v["epic_key"], v["status"], v["reason"], v["type"], v["priority"], v["reporter"]) == (
        "DEMO-E1", "todo", "Moved by hand", "task", "medium", "owner-tok")
    assert v["refs"] == [] and v["links_summary"] == {}
    assert (await repo.first("select key, seq from epics where key='DEMO-E1'"))["seq"] == 1
    ev = await repo.first("select * from events where kind='task.created' and subject_id=?", (v["id"],))
    assert (ev["actor"], ev["via"], json.loads(ev["payload"])["key"]) == ("owner-tok", "api", "DEMO-1")
    # board progress counts the new task
    b = (await req(client_for, app, h, "GET", "/api/epics/DEMO-E1")).json()
    assert b["epic"]["progress"] == {"done": 0, "total": 1} and b["tasks"][0]["key"] == "DEMO-1"


async def test_create_task_validation(make_app, client_for):
    app, repo, h, _ = await world(make_app, client_for)
    for bad in ({"description": "  "}, {"done_when": ""}, {"owner": " "}, {"summary": "x" * 301},
                {"refs": ["nope"]}, {"waiting_on": None}, {"type": "story"}):
        assert (await mk_task(client_for, app, h, **bad)).status_code == 422, bad
    r = await mk_task(client_for, app, h, epic_key="SAMPLE-E1")
    assert r.status_code == 422 and "SAMPLE-E1" in r.json()["detail"]
    assert (await mk_task(client_for, app, h, epic_key="DEMO-E9")).status_code == 404
    assert (await mk_task(client_for, app, h, project="NOPE")).status_code == 404
    assert (await repo.first("select count(*) as n from tasks"))["n"] == 0


async def test_create_task_with_item_links_it(make_app, client_for):
    app, repo, h, _ = await world(make_app, client_for)
    i = await add_item(repo, "1", cat="in_progress")
    r = await mk_task(client_for, app, h, epic_key="DEMO-E1", item_id=i, summary="From card")
    assert r.status_code == 201
    v = r.json()
    assert v["status"] == "in_progress" and v["links_summary"] == {"kanban": {"count": 1, "state": "running"}}
    item = await repo.first("select * from items where id=?", (i,))
    assert (item["task_id"], item["filing"]) == (v["id"], "epic")
    assert "item.linked" in await kinds(repo, "item")
    await invariant(repo)
    assert (await mk_task(client_for, app, h, item_id=999)).status_code == 404


async def test_linked_task_status_is_not_manual(make_app, client_for):
    app, repo, h, _ = await world(make_app, client_for)
    i = await add_item(repo, "1", cat="review")
    await mk_task(client_for, app, h, item_id=i)
    for s in ("todo", "in_progress", "review", "done"):
        r = await req(client_for, app, h, "POST", "/api/tasks/DEMO-1/status", {"status": s})
        assert (r.status_code, r.json()["detail"]) == (422, "status follows its links")
    r = await req(client_for, app, h, "POST", "/api/tasks/DEMO-1/status", {"status": "canceled"})
    assert r.status_code == 200 and r.json()["status"] == "canceled" and r.json()["reason"] == "Canceled"
    assert "task.status_changed" in await kinds(repo, "task")
    # without links the status is manual
    await mk_task(client_for, app, h)
    r = await req(client_for, app, h, "POST", "/api/tasks/DEMO-2/status", {"status": "in_progress"})
    assert (r.status_code, r.json()["status"], r.json()["reason"]) == (200, "in_progress", "Moved by hand")
    assert (await req(client_for, app, h, "POST", "/api/tasks/DEMO-9/status", {"status": "todo"})).status_code == 404


async def test_agent_done_needs_human_confirmation(make_app, client_for):
    app, repo, h, hh = await world(make_app, client_for)
    await mk_task(client_for, app, h, epic_key="DEMO-E1")
    r = await req(client_for, app, h, "POST", "/api/tasks/DEMO-1/status", {"status": "done"})
    assert (r.json()["status"], r.json()["flags"]) == ("review", ["awaiting_confirmation"])
    assert r.json()["reason"] == "Done by an agent; waiting for a human to confirm"
    e = (await req(client_for, app, h, "GET", "/api/epics/DEMO-E1")).json()["epic"]
    assert (e["column"], e["review_owner"]) == ("review", "human")
    r = await req(client_for, app, h, "POST", "/api/tasks/DEMO-1/confirm-done", {})
    assert r.status_code == 403
    async with client_for(app) as c:
        r = await c.post("/api/tasks/DEMO-1/confirm-done", content="{}", headers=hh)
        assert r.status_code == 415
    r = await req(client_for, app, hh, "POST", "/api/tasks/DEMO-1/confirm-done", {})
    assert (r.status_code, r.json()["status"], r.json()["flags"]) == (200, "done", [])
    assert "task.done_confirmed" in await kinds(repo, "task")
    e = (await req(client_for, app, h, "GET", "/api/epics/DEMO-E1")).json()["epic"]
    assert (e["column"], e["progress"]) == ("done", {"done": 1, "total": 1})
    # a human's own move to done confirms at once; an agent moving it again needs a new confirmation
    await mk_task(client_for, app, h)
    r = await req(client_for, app, hh, "POST", "/api/tasks/DEMO-2/status", {"status": "done"})
    assert r.json()["status"] == "done"
    await req(client_for, app, h, "POST", "/api/tasks/DEMO-2/status", {"status": "review"})
    r = await req(client_for, app, h, "POST", "/api/tasks/DEMO-2/status", {"status": "done"})
    assert r.json()["status"] == "review"
    # confirm only applies to a task awaiting confirmation
    await mk_task(client_for, app, h)
    assert (await req(client_for, app, hh, "POST", "/api/tasks/DEMO-3/confirm-done", {})).status_code == 422


async def test_merge_moves_links_and_aliases_key(make_app, client_for):
    app, repo, h, _ = await world(make_app, client_for)
    a, b = await add_item(repo, "1", cat="done"), await add_item(repo, "2", cat="review")
    await mk_task(client_for, app, h, item_id=a, refs=["OPS-1"])
    await mk_task(client_for, app, h, epic_key="DEMO-E1", item_id=b)
    r = await req(client_for, app, h, "POST", "/api/tasks/DEMO-1/merge", {"into": "DEMO-2"})
    assert r.status_code == 200
    v = r.json()
    assert v["key"] == "DEMO-2" and v["refs"] == ["DEMO-1", "OPS-1"]
    assert v["links_summary"] == {"kanban": {"count": 2, "state": "done"}}
    gone = await task_row(repo, "DEMO-1")
    assert (gone["status"], gone["merged_into"]) == ("canceled", v["id"])
    d = (await req(client_for, app, h, "GET", "/api/tasks/DEMO-1")).json()
    assert (d["status"], d["reason"]) == ("canceled", "Merged into DEMO-2")
    await invariant(repo)
    assert (await repo.first("select epic_id from items where id=?", (a,)))["epic_id"] is not None
    assert "task.merged" in await kinds(repo, "task")
    await mk_task(client_for, app, h, project="SAMPLE")
    await mk_task(client_for, app, h)
    for src, into, code in (("DEMO-3", "DEMO-3", 422), ("DEMO-3", "SAMPLE-1", 422), ("DEMO-1", "DEMO-3", 422),
                            ("DEMO-3", "DEMO-1", 422), ("DEMO-3", "DEMO-9", 404)):
        r = await req(client_for, app, h, "POST", f"/api/tasks/{src}/merge", {"into": into})
        assert r.status_code == code, (src, into)


async def test_link_and_unlink_keep_invariant(make_app, client_for):
    app, repo, h, _ = await world(make_app, client_for)
    i = await add_item(repo, "1", cat="in_progress")
    await mk_task(client_for, app, h, epic_key="DEMO-E1")
    await mk_task(client_for, app, h)
    r = await req(client_for, app, h, "POST", f"/api/items/{i}/link", {"task_key": "DEMO-1"})
    assert (r.status_code, r.json()["filing"], r.json()["task_id"]) == (200, "epic", (await task_row(repo, "DEMO-1"))["id"])
    await invariant(repo)
    e = (await req(client_for, app, h, "GET", "/api/epics/DEMO-E1")).json()["epic"]
    assert e["column"] == "in_progress"
    r = await req(client_for, app, h, "POST", f"/api/items/{i}/link", {"task_key": "DEMO-2"})
    assert r.json()["filing"] == "standalone"
    await invariant(repo)
    e = (await req(client_for, app, h, "GET", "/api/epics/DEMO-E1")).json()["epic"]
    assert e["column"] == "backlog"
    r = await req(client_for, app, h, "POST", f"/api/items/{i}/unlink")
    assert (r.status_code, r.json()["filing"], r.json()["task_id"]) == (200, "unfiled", None)
    await invariant(repo)
    assert [k for k in await kinds(repo, "item")] == ["item.linked", "item.linked", "item.unlinked"]
    assert (await req(client_for, app, h, "POST", f"/api/items/{i}/link", {"task_key": "DEMO-9"})).status_code == 404
    assert (await req(client_for, app, h, "POST", "/api/items/999/link", {"task_key": "DEMO-1"})).status_code == 404


async def test_filing_epic_creates_auto_task(make_app, client_for):
    app, repo, h, _ = await world(make_app, client_for)
    i = await repo.execute(
        "insert into items(source,external_id,filing,title,url,status_category,owner,waiting_on,"
        "last_activity_at,created_at,updated_at) values('github','7','unfiled','Fix it',"
        "'https://example.test/pr/7','review','','agent:a',1,1,1)")
    r = await req(client_for, app, h, "POST", f"/api/items/{i}/filing", {"filing": "epic", "epic_key": "DEMO-E1"})
    assert r.status_code == 200
    t = await task_row(repo, "DEMO-1")
    assert (t["summary"], t["description"], t["done_when"], t["owner"], t["reporter"], t["epic_id"]) == (
        "Fix it", "Created from https://example.test/pr/7", "The linked work is live.", "github", "owner-tok",
        r.json()["epic_id"])
    assert t["origin_item_id"] == i and r.json()["task_id"] == t["id"]
    await invariant(repo)
    # filing again under another epic of the project moves the item's task, no new task
    await mk_epic(client_for, app, h, title="E2")
    r = await req(client_for, app, h, "POST", f"/api/items/{i}/filing", {"filing": "epic", "epic_key": "DEMO-E2"})
    assert (await repo.first("select count(*) as n from tasks"))["n"] == 1
    assert (await task_row(repo, "DEMO-1"))["epic_id"] == r.json()["epic_id"]
    await invariant(repo)
    # standalone: the task moves to No epic
    r = await req(client_for, app, h, "POST", f"/api/items/{i}/filing", {"filing": "standalone"})
    assert r.json()["filing"] == "standalone" and (await task_row(repo, "DEMO-1"))["epic_id"] is None
    await invariant(repo)
    # ignored: unlinked
    r = await req(client_for, app, h, "POST", f"/api/items/{i}/filing", {"filing": "ignored"})
    assert (r.json()["filing"], r.json()["task_id"]) == ("ignored", None)
    await invariant(repo)
    # an unfiled item filed standalone gets a No-epic task in its project
    j = await add_item(repo, "8", cat="todo", project_id=1)
    r = await req(client_for, app, h, "POST", f"/api/items/{j}/filing", {"filing": "standalone"})
    assert (await task_row(repo, "DEMO-2"))["epic_id"] is None and r.json()["filing"] == "standalone"
    await invariant(repo)


async def test_patch_task_epic_moves_links(make_app, client_for):
    app, repo, h, _ = await world(make_app, client_for)
    await mk_epic(client_for, app, h, title="E2")
    i = await add_item(repo, "1", cat="in_progress")
    await mk_task(client_for, app, h, epic_key="DEMO-E1", item_id=i)
    r = await req(client_for, app, h, "PATCH", "/api/tasks/DEMO-1",
                  {"epic_key": "DEMO-E2", "summary": "  Renamed ", "refs": ["OPS-2"], "type": "bug"})
    v = r.json()
    assert (r.status_code, v["epic_key"], v["summary"], v["refs"], v["type"]) == (
        200, "DEMO-E2", "Renamed", ["OPS-2"], "bug")
    await invariant(repo)
    cols = {k: (await req(client_for, app, h, "GET", f"/api/epics/{k}")).json()["epic"]["column"]
            for k in ("DEMO-E1", "DEMO-E2")}
    assert cols == {"DEMO-E1": "backlog", "DEMO-E2": "in_progress"}
    r = await req(client_for, app, h, "PATCH", "/api/tasks/DEMO-1", {"epic_key": None})
    assert r.json()["epic_key"] is None
    await invariant(repo)
    assert "task.updated" in await kinds(repo, "task")
    for bad in ({"summary": None}, {"description": " "}, {"epic_key": "SAMPLE-E1"}, {"waiting_on": None}, {}):
        assert (await req(client_for, app, h, "PATCH", "/api/tasks/DEMO-1", bad)).status_code == 422, bad


async def test_task_seq_race_is_409_not_500(make_app, client_for):
    app, repo, h, _ = await world(make_app, client_for)
    await mk_task(client_for, app, h)
    orig = repo.first

    async def stale(sql, args=()):
        if "max(seq)" in sql and "tasks" in sql:
            return {"m": 0}
        return await orig(sql, args)

    repo.first = stale
    app.state.repo = repo
    r = await mk_task(client_for, app, h)
    assert r.status_code == 409


async def test_relations_accept_tasks(make_app, client_for):
    app, repo, h, _ = await world(make_app, client_for)
    a = (await mk_task(client_for, app, h)).json()["id"]
    b = (await mk_task(client_for, app, h)).json()["id"]
    r = await req(client_for, app, h, "POST", "/api/relations",
                  {"from_type": "task", "from_id": a, "to_type": "task", "to_id": b})
    assert r.status_code == 201
    assert (await req(client_for, app, h, "POST", "/api/relations",
                      {"from_type": "task", "from_id": 99, "to_type": "task", "to_id": b})).status_code == 404


async def test_task_reads_routes(make_app, client_for):
    app, repo, h, _ = await world(make_app, client_for)
    await mk_task(client_for, app, h, epic_key="DEMO-E1")
    rh = bearer(await add_token(repo, name="reader", scopes="read"))
    b = await req(client_for, app, rh, "GET", "/api/projects/DEMO/tasks")
    assert b.status_code == 200 and b.json()["lanes"][0]["tasks"]["todo"][0]["key"] == "DEMO-1"
    assert (await req(client_for, app, rh, "GET", "/api/projects/NOPE/tasks")).status_code == 404
    d = await req(client_for, app, rh, "GET", "/api/tasks/DEMO-1")
    assert d.status_code == 200 and d.json()["links"] == [] and d.json()["events"][0]["kind"] == "task.created"
    assert (await req(client_for, app, rh, "GET", "/api/tasks/DEMO-9")).status_code == 404
    assert (await mk_task(client_for, app, rh)).status_code == 403


async def test_human_scope_token_is_human(make_app, client_for):
    from loopboard.auth import Principal

    assert Principal("a@example.test", "access", frozenset({"read"})).is_human
    assert Principal("p", "token", frozenset({"read", "write", "human"})).is_human
    assert not Principal("bot", "token", frozenset({"read", "write"})).is_human


def _make_token(*args):
    script = Path(__file__).resolve().parents[1] / "scripts" / "make_token.py"
    return subprocess.run([sys.executable, str(script), "--name", "x", *args], capture_output=True, text=True)


def test_make_token_accepts_human_scope_not_with_ingest():
    ok = _make_token("--scopes", "read,write,human")
    assert ok.returncode == 0 and "'read,write,human'" in ok.stdout
    for bad in (["--scopes", "ingest,human", "--source", "kanban"], ["--scopes", "human"]):
        assert _make_token(*bad).returncode != 0, bad
