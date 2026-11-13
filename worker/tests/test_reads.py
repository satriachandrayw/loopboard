import json

from loopboard import reads
from loopboard.model import DAY
from tests.test_auth import add_token, bearer

NOW = 1_800_000_000
H = 3600


async def mk_epic(repo, key="DEMO-E1", project="DEMO", title="E", manual="todo", stage="build",
                  waiting_on=None, last=NOW, done_at=None, confirmed=None, board="todo"):
    p = await repo.first("select id from projects where key=?", (project,))
    if p is None:
        pid = await repo.execute("insert into projects(key,name,created_at) values(?,?,1)", (project, project))
    else:
        pid = p["id"]
    seq = int(key.split("-E")[1])
    return await repo.execute(
        "insert into epics(project_id,seq,key,title,manual_column,board_column,stage,waiting_on,"
        "done_confirmed_at,done_at,last_activity_at,created_at,updated_at) values(?,?,?,?,?,?,?,?,?,?,?,1,1)",
        (pid, seq, key, title, manual, board, stage, waiting_on, confirmed, done_at, last))


async def mk_item(repo, ext, epic_id=None, cat="in_progress", filing=None, waiting_on="agent:a", last=NOW,
                  merged=None, live=None, source="kanban", title="t", reason=None, project_id=None):
    filing = filing or ("epic" if epic_id else "unfiled")
    return await repo.execute(
        "insert into items(source,external_id,epic_id,project_id,filing,title,status_category,waiting_on,"
        "blocked_reason,last_activity_at,merged_at,live_at,created_at,updated_at)"
        " values(?,?,?,?,?,?,?,?,?,?,?,?,1,1)",
        (source, ext, epic_id, project_id, filing, title, cat, waiting_on, reason, last, merged, live))


def col(b, name):
    return next(c for c in b["columns"] if c["column"] == name)


async def test_board_five_columns_in_order(repo):
    b = await reads.board(repo, now=NOW)
    assert [(c["column"], c["label"]) for c in b["columns"]] == [
        ("backlog", "Backlog"), ("todo", "Todo"), ("in_progress", "In progress"),
        ("review", "Review"), ("done", "Done")]


async def test_board_card_has_contract_fields(repo):
    e = await mk_epic(repo, waiting_on="agent:a", last=NOW - 100)
    await mk_item(repo, "1", e, "in_progress", last=NOW - 10)
    await mk_item(repo, "2", e, "done", last=NOW - 5)
    b = await reads.board(repo, now=NOW)
    card = col(b, "in_progress")["cards"][0]
    assert card == {"id": e, "key": "DEMO-E1", "title": "E", "goal": None, "project_key": "DEMO",
                    "column": "in_progress",
                    "stage": "build", "progress": {"done": 1, "total": 2}, "owner": None,
                    "waiting_on": "agent:a", "waiting_since": NOW - 10, "stalled": False,
                    "flags": [], "review_owner": None}
    assert col(b, "in_progress")["count"] == 1


async def _review_epics(repo, n):
    for k in range(1, n + 1):
        e = await mk_epic(repo, key=f"DEMO-E{k}")
        await mk_item(repo, str(k), e, "review")


async def test_board_warns_when_review_has_four_cards(repo):
    await _review_epics(repo, 4)
    assert col(await reads.board(repo, now=NOW), "review")["warn"] is True


async def test_board_no_warn_with_three(repo):
    await _review_epics(repo, 3)
    assert col(await reads.board(repo, now=NOW), "review")["warn"] is False


async def test_board_hides_done_after_seven_days(repo):
    e = await mk_epic(repo, done_at=NOW - 7 * DAY, confirmed=1)
    await mk_item(repo, "1", e, "done")
    assert col(await reads.board(repo, now=NOW), "done")["count"] == 1
    assert col(await reads.board(repo, now=NOW + 1), "done")["count"] == 0


async def test_board_excludes_canceled(repo):
    await mk_epic(repo, manual="canceled")
    b = await reads.board(repo, now=NOW)
    assert sum(c["count"] for c in b["columns"]) == 0


async def test_board_filters_by_project_and_waiting_on(repo):
    await mk_epic(repo, key="DEMO-E1", waiting_on="agent:a")
    await mk_epic(repo, key="DEMO-E2", waiting_on="human:owner")
    await mk_epic(repo, key="OTHR-E1", project="OTHR", waiting_on="human:owner")
    keys = lambda b: sorted(c["key"] for x in b["columns"] for c in x["cards"])  # noqa: E731
    assert keys(await reads.board(repo, now=NOW, project_key="DEMO")) == ["DEMO-E1", "DEMO-E2"]
    assert keys(await reads.board(repo, now=NOW, waiting_on="human")) == ["DEMO-E2", "OTHR-E1"]
    assert keys(await reads.board(repo, now=NOW, project_key="DEMO", waiting_on="human")) == ["DEMO-E2"]


async def test_board_stalled_flag_matches_stall_rule(repo):
    await repo.execute("insert into sources(name, stall_hours, updated_at) values('kanban', 2, 1)")
    e = await mk_epic(repo, last=NOW - 10 * H)
    await mk_item(repo, "1", e, "in_progress", last=NOW - 2 * H)
    assert col(await reads.board(repo, now=NOW), "in_progress")["cards"][0]["stalled"] is False
    assert col(await reads.board(repo, now=NOW + 1), "in_progress")["cards"][0]["stalled"] is True


async def test_needs_you_oldest_first_with_reasons(repo):
    e1 = await mk_epic(repo, key="DEMO-E1", title="late", waiting_on="human:owner", last=NOW - 10)
    e2 = await mk_epic(repo, key="DEMO-E2", title="old", last=NOW - 500)
    await mk_item(repo, "1", e2, "review", waiting_on="human:owner", last=NOW - 500)
    e3 = await mk_epic(repo, key="DEMO-E3", title="spec", stage="spec", waiting_on="human:owner",
                       last=NOW - 100)
    e4 = await mk_epic(repo, key="DEMO-E4", title="agent")
    await mk_item(repo, "4", e4, "in_progress")
    e5 = await mk_epic(repo, key="DEMO-E5", title="blk", last=NOW - 700)
    await mk_item(repo, "5", e5, "blocked", waiting_on="human:owner", reason="needs_input", last=NOW - 700)
    e6 = await mk_epic(repo, key="DEMO-E6", title="merged", last=NOW - 50)
    await mk_item(repo, "6", e6, "review", waiting_on="agent:a", merged=NOW - 60, last=NOW - 50)
    rows = await reads.needs_you(repo, now=NOW)
    by = {r["ref"]: r for r in rows}
    assert [r["ref"] for r in rows] == ["DEMO-E5", "DEMO-E2", "DEMO-E3", "DEMO-E6", "DEMO-E1"]
    assert "DEMO-E4" not in by
    assert by["DEMO-E2"]["reasons"] == ["review · you"]
    assert by["DEMO-E3"]["reasons"] == ["waiting on you", "awaiting your approval"]
    assert by["DEMO-E5"]["reasons"] == ["blocked: needs your input"]
    assert by["DEMO-E6"]["reasons"] == ["merged, not live"]
    assert by["DEMO-E1"]["kind"] == "epic" and by["DEMO-E1"]["id"] == e1


async def test_needs_you_includes_standalone_item_waiting_on_human(repo):
    i = await mk_item(repo, "9", None, "review", filing="standalone", waiting_on="human:owner", last=NOW - 5)
    await mk_item(repo, "10", None, "done", filing="standalone", waiting_on="human:owner")
    await mk_item(repo, "11", None, "review", filing="unfiled", waiting_on="human:owner")
    rows = await reads.needs_you(repo, now=NOW)
    assert [(r["kind"], r["id"], r["ref"], r["reasons"]) for r in rows] == [
        ("item", i, "kanban:9", ["waiting on you"])]


async def _stall_setup(repo):
    await repo.execute("insert into sources(name, stall_hours, updated_at) values('kanban', 1, 1)")
    e = await mk_epic(repo, waiting_on="human:owner", last=NOW - 9 * H)
    await mk_item(repo, "1", e, "in_progress", waiting_on="agent:a", last=NOW - 5 * H)
    await mk_item(repo, "2", None, "todo", filing="standalone", waiting_on=None, last=NOW - 3 * H)
    await mk_item(repo, "3", None, "todo", filing="unfiled", last=NOW - 30 * H)


async def test_stalled_grouped_by_waiting_group(repo):
    await _stall_setup(repo)
    rows = await reads.stalled(repo, now=NOW)
    refs = {r["ref"]: r for r in rows}
    assert set(refs) == {"DEMO-E1", "kanban:1", "kanban:2"}
    assert refs["DEMO-E1"]["waiting_group"] == "human"
    assert refs["kanban:1"]["waiting_group"] == "agent"
    assert refs["kanban:2"]["waiting_group"] == "source"
    assert refs["kanban:2"]["stalled_for_hours"] == 3.0
    assert refs["kanban:1"]["source"] == "kanban" and refs["kanban:1"]["external_id"] == "1"
    assert [r["waiting_since"] for r in rows] == sorted(r["waiting_since"] for r in rows)


async def test_stalled_filter_agent_only(repo):
    await _stall_setup(repo)
    rows = await reads.stalled(repo, now=NOW, waiting_on="agent")
    assert [r["ref"] for r in rows] == ["kanban:1"]
    assert all(r["waiting_group"] == "agent" for r in rows)


async def test_unfiled_lists_only_unfiled_oldest_first(repo):
    e = await mk_epic(repo)
    b = await mk_item(repo, "b", None, "todo", last=20)
    a = await mk_item(repo, "a", None, "todo", last=10)
    await mk_item(repo, "c", e, "todo")
    await mk_item(repo, "d", None, "canceled", waiting_on=None, last=5)
    await mk_item(repo, "e", None, "todo", filing="standalone")
    rows = await reads.unfiled(repo, now=NOW)
    assert [r["id"] for r in rows] == [a, b]
    assert set(rows[0]) == {"id", "source", "external_id", "title", "url", "owner", "waiting_on",
                            "last_activity_at", "project_key", "status_category", "category",
                            "merged_at", "live_at"}


async def test_epic_detail_groups_tasks_into_five_groups(repo):
    e = await mk_epic(repo, stage="plan")
    await mk_item(repo, "1", e, "todo")
    await mk_item(repo, "2", e, "in_progress")
    await mk_item(repo, "3", e, "blocked")
    await mk_item(repo, "4", e, "review")
    await mk_item(repo, "5", e, "done", waiting_on=None)
    await mk_item(repo, "6", e, "review", merged=1, live=2)
    await mk_item(repo, "7", e, "canceled", waiting_on=None)
    other = await mk_item(repo, "8", e, "todo")
    await repo.execute("insert into relations(kind,from_type,from_id,to_type,to_id,created_at) "
                       "values('blocks','item',?,'epic',999,1)", (other,))
    await repo.execute("insert into relations(kind,from_type,from_id,to_type,to_id,created_at) "
                       "values('blocks','epic',500,'epic',501,1)")
    d = await reads.epic_detail(repo, key="DEMO-E1", now=NOW)
    t = d["tasks"]
    assert list(t) == ["todo", "in_progress", "blocked", "review", "done"]
    assert [len(t[g]) for g in t] == [2, 1, 1, 1, 2]
    assert d["epic"]["key"] == "DEMO-E1" and d["epic"]["goal"] is None
    assert "board_column" not in d["epic"]
    # stored column is todo (stale); the response carries only the derived one
    assert d["epic"]["column"] == "in_progress"
    assert len(d["relations"]) == 1


async def test_epic_detail_events_newest_first_limit_50(repo):
    e = await mk_epic(repo)
    i = await mk_item(repo, "1", e, "todo")
    other = await mk_item(repo, "2", None, "todo")
    for n in range(60):
        await repo.execute("insert into events(at,actor,via,subject_type,subject_id,kind,payload) "
                           "values(?,?,?,?,?,?,?)",
                           (100 + n, "x", "api", "item" if n % 2 else "epic", i if n % 2 else e, "k",
                            json.dumps({"n": n})))
    await repo.execute("insert into events(at,actor,via,subject_type,subject_id,kind,payload) "
                       "values(1000,'x','api','item',?,'k','{}')", (other,))
    d = await reads.epic_detail(repo, key="DEMO-E1", now=NOW)
    assert len(d["events"]) == 50
    assert [ev["payload"]["n"] for ev in d["events"]][:3] == [59, 58, 57]


async def test_epic_detail_unknown_key_is_404(make_app, client_for):
    app, repo = make_app(clock=lambda: NOW)
    t = await add_token(repo, scopes="read")
    async with client_for(app) as c:
        r = await c.get("/api/epics/DEMO-E9", headers=bearer(t))
        assert r.status_code == 404
        await mk_epic(repo)
        r = await c.get("/api/epics/DEMO-E1", headers=bearer(t))
        assert r.status_code == 200 and r.json()["epic"]["key"] == "DEMO-E1"
        assert (await c.get("/api/board?waiting_on=nobody", headers=bearer(t))).status_code == 422
        assert (await c.get("/api/board?waiting_on=human", headers=bearer(t))).status_code == 200
        for p in ("projects", "needs-you", "stalled", "unfiled"):
            assert (await c.get(f"/api/{p}", headers=bearer(t))).status_code == 200
        assert (await c.get("/api/board")).status_code == 401


async def test_epic_detail_backlog_task_folds_into_todo(repo):
    e = await mk_epic(repo)
    await mk_item(repo, "1", e, "backlog")
    d = await reads.epic_detail(repo, key="DEMO-E1", now=NOW)
    assert [t["ref"] for t in d["tasks"]["todo"]] == ["kanban:1"]


async def test_epic_detail_with_60_items_stays_under_param_cap(repo):
    e = await mk_epic(repo)
    ids = [await mk_item(repo, str(n), e, "todo") for n in range(60)]
    await repo.execute("insert into relations(kind,from_type,from_id,to_type,to_id,created_at) "
                       "values('blocks','item',?,'epic',999,1)", (ids[-1],))
    await repo.execute("insert into events(at,actor,via,subject_type,subject_id,kind,payload) "
                       "values(5,'x','api','item',?,'k','{}')", (ids[-1],))
    seen = []
    orig = repo.query

    async def spy(sql, args=()):
        seen.append(len(args))
        return await orig(sql, args)

    repo.query = spy
    d = await reads.epic_detail(repo, key="DEMO-E1", now=NOW)
    assert len(d["tasks"]["todo"]) == 60 and len(d["relations"]) == 1 and len(d["events"]) == 1
    assert max(seen) <= 4


async def test_stalled_skips_items_of_canceled_epic(repo):
    e = await mk_epic(repo, manual="canceled", board="canceled")
    await mk_item(repo, "1", e, "in_progress", last=NOW - 100 * H)
    await mk_item(repo, "2", None, "in_progress", filing="standalone", last=NOW - 100 * H)
    assert [r["ref"] for r in await reads.stalled(repo, now=NOW)] == ["kanban:2"]


async def _pid(repo, key):
    return (await repo.first("select id from projects where key=?", (key,)))["id"]


async def test_unfiled_carries_project_and_effective_category(repo):
    await mk_epic(repo)
    pid = await _pid(repo, "DEMO")
    a = await mk_item(repo, "a", None, "review", merged=1, live=2, last=10, project_id=pid)
    b = await mk_item(repo, "b", None, "done", waiting_on=None, last=20)
    rows = {r["id"]: r for r in await reads.unfiled(repo, now=NOW)}
    assert rows[a]["project_key"] == "DEMO" and rows[a]["category"] == "done"
    assert rows[a]["status_category"] == "review" and rows[a]["live_at"] == 2
    assert rows[b]["project_key"] is None and rows[b]["category"] == "done"


async def test_unfiled_project_filter(repo):
    await mk_epic(repo)
    await mk_epic(repo, key="OTHER-E1", project="OTHER")
    a = await mk_item(repo, "a", None, "todo", project_id=await _pid(repo, "DEMO"))
    await mk_item(repo, "b", None, "todo", project_id=await _pid(repo, "OTHER"))
    await mk_item(repo, "c", None, "todo")
    assert [r["id"] for r in await reads.unfiled(repo, now=NOW, project_key="DEMO")] == [a]


async def test_needs_you_project_filter(repo):
    await mk_epic(repo, waiting_on="human:owner")
    await mk_epic(repo, key="OTHER-E1", project="OTHER", waiting_on="human:owner")
    i = await mk_item(repo, "9", None, "review", filing="standalone", waiting_on="human:owner",
                      project_id=await _pid(repo, "OTHER"))
    await mk_item(repo, "8", None, "review", filing="standalone", waiting_on="human:owner",
                  project_id=await _pid(repo, "DEMO"))
    rows = await reads.needs_you(repo, now=NOW, project_key="OTHER")
    assert sorted((r["kind"], r["ref"]) for r in rows) == [("epic", "OTHER-E1"), ("item", "kanban:9")]
    assert any(r["id"] == i for r in rows)


async def test_stalled_project_filter_uses_item_or_epic_project(repo):
    await repo.execute("insert into sources(name, stall_hours, updated_at) values('kanban', 1, 1)")
    d = await mk_epic(repo, last=NOW - 9 * H)
    o = await mk_epic(repo, key="OTHER-E1", project="OTHER", last=NOW - 9 * H)
    await mk_item(repo, "1", d, "in_progress", last=NOW - 5 * H)
    await mk_item(repo, "2", o, "in_progress", last=NOW - 5 * H)
    await mk_item(repo, "3", None, "todo", filing="standalone", last=NOW - 5 * H,
                  project_id=await _pid(repo, "OTHER"))
    rows = await reads.stalled(repo, now=NOW, project_key="OTHER")
    assert {r["ref"] for r in rows} == {"OTHER-E1", "kanban:2", "kanban:3"}


async def test_list_routes_accept_project_param(make_app, client_for):
    app, repo = make_app(clock=lambda: NOW)
    t = await add_token(repo, scopes="read")
    await mk_epic(repo, waiting_on="human:owner")
    async with client_for(app) as c:
        for p in ("needs-you", "stalled", "unfiled"):
            r = await c.get(f"/api/{p}?project=NOPE", headers=bearer(t))
            assert r.status_code == 200 and r.json() == []
        r = await c.get("/api/needs-you?project=DEMO", headers=bearer(t))
        assert [x["ref"] for x in r.json()] == ["DEMO-E1"]


async def test_board_card_carries_goal(make_app, client_for):
    from tests.test_writes import mk_epic as post_epic, mk_project, req, setup

    app, repo, h = await setup(make_app)
    await mk_project(client_for, app, h)
    assert (await post_epic(client_for, app, h, title="With")).status_code == 201
    await mk_epic(repo, key="DEMO-E2", title="Without", manual="backlog", board="backlog", waiting_on="agent:a")
    rh = bearer(await add_token(repo, name="reader", scopes="read"))
    b = (await req(client_for, app, rh, "GET", "/api/board")).json()
    cards = {c["title"]: c for column in b["columns"] for c in column["cards"]}
    assert cards["With"]["goal"] == "Demo goal."
    assert "goal" in cards["Without"] and cards["Without"]["goal"] is None
