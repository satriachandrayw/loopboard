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


async def mk_task(repo, *, project_id=None, epic_id=None, summary="t", status="todo", waiting_on="agent:a",
                  last=NOW, confirmed=None, owner="owner", refs="[]", merged_into=None):
    """A task row; the key is <PROJECT>-<next seq>. project defaults to the epic's, else DEMO."""
    if project_id is None and epic_id is not None:
        project_id = (await repo.first("select project_id from epics where id=?", (epic_id,)))["project_id"]
    if project_id is None:
        p = await repo.first("select id from projects where key='DEMO'")
        project_id = p["id"] if p else await repo.execute(
            "insert into projects(key,name,created_at) values('DEMO','DEMO',1)")
    pk = (await repo.first("select key from projects where id=?", (project_id,)))["key"]
    seq = (await repo.first("select coalesce(max(seq),0)+1 as n from tasks where project_id=?", (project_id,)))["n"]
    return await repo.execute(
        "insert into tasks(project_id,epic_id,seq,key,summary,description,done_when,status,owner,waiting_on,"
        "reporter,refs,merged_into,done_confirmed_at,last_activity_at,created_at,updated_at)"
        " values(?,?,?,?,?,'d','w',?,?,?,'tester',?,?,?,?,1,1)",
        (project_id, epic_id, seq, f"{pk}-{seq}", summary, status, owner, waiting_on, refs, merged_into,
         confirmed, last))


async def mk_item(repo, ext, epic_id=None, cat="in_progress", filing=None, waiting_on="agent:a", last=NOW,
                  merged=None, live=None, source="kanban", title="t", reason=None, project_id=None,
                  task_id=None):
    """An item; a filed one (epic or standalone) gets its own task, as the 0002 backfill does,
    unless task_id is given."""
    filing = filing or ("epic" if epic_id or task_id else "unfiled")
    if filing in ("epic", "standalone") and task_id is None:
        task_id = await mk_task(repo, project_id=project_id, epic_id=epic_id, summary=title,
                                status="canceled" if cat == "canceled" else "todo",
                                waiting_on=waiting_on, last=last)
    return await repo.execute(
        "insert into items(source,external_id,epic_id,project_id,filing,title,status_category,waiting_on,"
        "blocked_reason,last_activity_at,merged_at,live_at,task_id,created_at,updated_at)"
        " values(?,?,?,?,?,?,?,?,?,?,?,?,?,1,1)",
        (source, ext, epic_id, project_id, filing, title, cat, waiting_on, reason, last, merged, live, task_id))


async def task_key(repo, item_id):
    return (await repo.first("select t.key from tasks t join items i on i.task_id = t.id where i.id=?",
                             (item_id,)))["key"]


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


async def test_needs_you_groups_by_answer_kind_oldest_first(repo):
    e1 = await mk_epic(repo, key="DEMO-E1", title="late", waiting_on="human:owner", last=NOW - 10)
    e2 = await mk_epic(repo, key="DEMO-E2", title="old", last=NOW - 500)
    await mk_item(repo, "1", e2, "review", waiting_on="human:owner", last=NOW - 500)
    await mk_epic(repo, key="DEMO-E3", title="spec", stage="spec", waiting_on="human:owner", last=NOW - 100)
    e4 = await mk_epic(repo, key="DEMO-E4", title="agent")
    await mk_item(repo, "4", e4, "in_progress")
    e5 = await mk_epic(repo, key="DEMO-E5", title="blk", last=NOW - 700)
    await mk_item(repo, "5", e5, "blocked", waiting_on="human:owner", reason="needs_input", last=NOW - 700)
    e6 = await mk_epic(repo, key="DEMO-E6", title="merged", last=NOW - 50)
    await mk_item(repo, "6", e6, "review", waiting_on="agent:a", merged=NOW - 60, last=NOW - 50)
    rows = await reads.needs_you(repo, now=NOW)
    assert [(r["ask_kind"], r["kind"], r["ref"]) for r in rows] == [
        ("decide", "task", "DEMO-3"), ("decide", "epic", "DEMO-E3"), ("decide", "epic", "DEMO-E1"),
        ("review", "task", "DEMO-1"), ("release", "release", "release:DEMO")]
    by = {r["ref"]: r for r in rows}
    assert by["DEMO-E1"]["id"] == e1 and by["DEMO-E3"]["reasons"] == ["waiting on you", "awaiting your approval"]
    assert by["DEMO-3"]["reasons"] == ["waiting on you", "blocked: needs your input"]
    assert by["DEMO-1"]["reasons"] == ["waiting on you"]
    for r in rows:
        assert set(r) == ROW_KEYS, r["ref"]


ROW_KEYS = {"kind", "id", "ref", "title", "project_key", "epic_key", "url", "waiting_on", "waiting_since", "reasons",
            "ask_kind", "question", "answer_how", "reply_code", "context", "auto", "missing_question", "items"}


async def ask(repo, key, **fields):
    sets = ", ".join(f"{k} = ?" for k in fields)
    await repo.execute(f"update tasks set {sets} where key = ?", (*fields.values(), key))


def pick(row, *keys):
    return tuple(row[k] for k in keys)


ASK = ("ask_kind", "question", "answer_how", "reply_code", "auto", "missing_question")


async def test_rule_confirm_when_agent_says_done(repo):
    e = await mk_epic(repo, waiting_on="agent:a")
    await mk_task(repo, epic_id=e, summary="said done", status="done")
    [r] = await reads.needs_you(repo, now=NOW)
    assert pick(r, *ASK) == ("confirm", "The agent says this is done. Is it?",
                             "Press Confirm done, or tell your agent what is missing.", None, True, False)
    assert (r["context"], r["items"], r["project_key"], r["epic_key"]) == ("d", None, "DEMO", "DEMO-E1")


async def test_rule_blocked_card_asks_what_next(repo):
    i = await mk_item(repo, "t_demo1", None, "blocked", filing="standalone", waiting_on="human:owner",
                      reason="needs_input")
    [r] = await reads.needs_you(repo, now=NOW)
    assert r["ref"] == await task_key(repo, i)
    assert pick(r, *ASK) == ("decide", "What should card t_demo1 do next?",
                             "Read the block reason on the card, then reply to your agent:", "t_demo1: <answer>",
                             True, False)


async def test_rule_open_pr_asks_merge(repo):
    t = await mk_task(repo, summary="pr", waiting_on="human:owner")
    await mk_item(repo, "owner/sample#7", None, "review", source="github", waiting_on="human:owner", task_id=t,
                  filing="standalone", project_id=1)
    await repo.execute("update items set url = 'https://example.test/pr/7'")
    [r] = await reads.needs_you(repo, now=NOW)
    assert pick(r, *ASK) == ("review", "Merge PR sample#7?", "Reply to your agent:", "merge sample#7", True, False)
    assert r["url"] == "https://example.test/pr/7"


async def test_rule_card_in_review_asks_approve(repo):
    await mk_item(repo, "t_demo2", None, "review", filing="standalone", waiting_on="human:owner")
    [r] = await reads.needs_you(repo, now=NOW)
    assert pick(r, *ASK) == ("review", "Approve card t_demo2?", "Reply to your agent:", "push t_demo2", True, False)


async def test_rule_no_question_recorded(repo):
    await mk_task(repo, summary="ask me", waiting_on="human:owner")
    [r] = await reads.needs_you(repo, now=NOW)
    assert pick(r, *ASK) == ("decide", "No question recorded yet.", "Ask your agent about this task:", "DEMO-1?",
                             True, True)


async def test_stored_question_wins(repo):
    t = await mk_task(repo, summary="pr", waiting_on="human:owner")
    await mk_item(repo, "owner/sample#7", None, "review", source="github", waiting_on="human:owner", task_id=t,
                  filing="standalone", project_id=1)
    await ask(repo, "DEMO-1", question="Ship the sample now?", answer_how="Reply:", reply_code="ship", ask_kind="review")
    [r] = await reads.needs_you(repo, now=NOW)
    assert pick(r, *ASK) == ("review", "Ship the sample now?", "Reply:", "ship", False, False)
    await ask(repo, "DEMO-1", ask_kind=None, reply_code=None)
    [r] = await reads.needs_you(repo, now=NOW)
    assert pick(r, "ask_kind", "reply_code") == ("decide", None)


async def test_not_before_moves_to_later(repo):
    await mk_task(repo, summary="later", waiting_on="human:owner", last=NOW - 900)
    await mk_task(repo, summary="now", waiting_on="human:owner", last=NOW - 10)
    await ask(repo, "DEMO-1", question="Go?", answer_how="Reply:", not_before=NOW + DAY)
    await ask(repo, "DEMO-2", question="Now?", answer_how="Reply:", not_before=NOW - DAY)
    rows = await reads.needs_you(repo, now=NOW)
    assert [pick(r, "ref", "ask_kind", "question") for r in rows] == [
        ("DEMO-2", "decide", "Now?"), ("DEMO-1", "later", "Go?")]
    await ask(repo, "DEMO-1", question=None, answer_how=None)
    rows = await reads.needs_you(repo, now=NOW)
    assert pick(rows[-1], "ask_kind", "question", "missing_question") == ("later", "No question recorded yet.", True)


async def test_release_row_folds_merged_not_live(repo):
    await repo.execute("insert into projects(key,name,created_at) values('DEMO','Demo app',1)")
    e = await mk_epic(repo, waiting_on="agent:a")
    await mk_item(repo, "owner/sample#1", e, "review", source="github", merged=NOW - 300, last=NOW - 300,
                  title="first change")
    await mk_item(repo, "owner/sample#2", e, "review", source="github", merged=NOW - 100, last=NOW - 100,
                  title="second change")
    await mk_item(repo, "owner/sample#3", e, "review", source="github", merged=NOW - 50, live=NOW - 40)
    await repo.execute("update items set url = 'https://example.test/pr/' || id")
    await mk_epic(repo, key="SAMPLE-E1", project="SAMPLE", waiting_on="agent:a")
    rows = await reads.needs_you(repo, now=NOW)
    assert [r["kind"] for r in rows] == ["release"]
    [r] = rows
    assert pick(r, "ref", "title", "project_key", "epic_key", "waiting_since", "reasons") == (
        "release:DEMO", "Demo app: 2 changes merged, not live", "DEMO", None, NOW - 300, ["merged, not live"])
    assert (r["waiting_on"], r["id"]) == (None, 1)
    assert pick(r, *ASK) == ("release", "Release Demo app to its live branch?", "Reply to your agent:",
                             "release demo", True, False)
    assert r["items"] == [
        {"ref": "github:owner/sample#1", "title": "first change", "url": "https://example.test/pr/1",
         "project_key": "DEMO"},
        {"ref": "github:owner/sample#2", "title": "second change", "url": "https://example.test/pr/2",
         "project_key": "DEMO"}]
    # filtered to another project: no release row
    assert await reads.needs_you(repo, now=NOW, project_key="SAMPLE") == []


async def _merged_pr(repo, ext, task_id, project_id=1, at=NOW - 200):
    return await mk_item(repo, ext, None, "review", source="github", merged=at, last=at, task_id=task_id,
                         filing="standalone", project_id=project_id, title=f"merged {ext}")


async def test_merged_and_open_pr_gives_review_row_and_release_item(repo):
    t = await mk_task(repo, summary="pr", waiting_on="human:owner")
    await _merged_pr(repo, "owner/sample#1", t)
    await mk_item(repo, "owner/sample#2", None, "review", source="github", waiting_on="human:owner", task_id=t,
                  filing="standalone", project_id=1)
    rows = await reads.needs_you(repo, now=NOW)
    assert [(r["kind"], r["ref"], r["ask_kind"]) for r in rows] == [
        ("task", "DEMO-1", "review"), ("release", "release:DEMO", "release")]
    assert rows[0]["question"] == "Merge PR sample#2?"
    assert [i["ref"] for i in rows[1]["items"]] == ["github:owner/sample#1"]


async def test_stored_question_and_merged_gives_own_row_and_release_item(repo):
    t = await mk_task(repo, summary="ask", waiting_on="human:owner")
    await _merged_pr(repo, "owner/sample#1", t)
    await ask(repo, "DEMO-1", question="Ship it?", answer_how="Reply:")
    rows = await reads.needs_you(repo, now=NOW)
    assert [(r["kind"], r["ask_kind"], r["question"]) for r in rows] == [
        ("task", "decide", "Ship it?"), ("release", "release", "Release DEMO to its live branch?")]
    assert rows[1]["title"] == "DEMO: 1 change merged, not live"


async def test_merged_only_human_task_without_question_is_covered_by_release(repo):
    t = await mk_task(repo, summary="merged", waiting_on="human:owner")
    await _merged_pr(repo, "owner/sample#1", t)
    assert [r["kind"] for r in await reads.needs_you(repo, now=NOW)] == ["release"]
    d = await reads.task_detail(repo, key="DEMO-1", now=NOW)
    assert d["ask"]["ask_kind"] == "release"


async def test_not_before_with_merged_only_folds_into_release_no_later_row(repo):
    t = await mk_task(repo, summary="later", waiting_on="human:owner")
    await _merged_pr(repo, "owner/sample#1", t)
    await ask(repo, "DEMO-1", not_before=NOW + DAY)
    rows = await reads.needs_you(repo, now=NOW)
    assert [(r["kind"], r["ask_kind"]) for r in rows] == [("release", "release")]
    assert [i["ref"] for i in rows[0]["items"]] == ["github:owner/sample#1"]
    # with its own question the task moves to Later; its merged work still folds into Release
    await ask(repo, "DEMO-1", question="Go?", answer_how="Reply:")
    rows = await reads.needs_you(repo, now=NOW)
    assert [(r["kind"], r["ask_kind"]) for r in rows] == [("release", "release"), ("task", "later")]


async def test_two_projects_two_release_rows(repo):
    t1 = await mk_task(repo, summary="a")
    await _merged_pr(repo, "owner/sample#1", t1, at=NOW - 300)
    await _merged_pr(repo, "owner/sample#2", t1, at=NOW - 250)
    pid = await repo.execute("insert into projects(key,name,created_at) values('SAMPLE','Sample app',1)")
    t2 = await mk_task(repo, project_id=pid, summary="b")
    await _merged_pr(repo, "owner/other#3", t2, project_id=pid, at=NOW - 100)
    rows = await reads.needs_you(repo, now=NOW)
    assert [(r["ref"], r["id"], r["title"], r["waiting_on"]) for r in rows] == [
        ("release:DEMO", 1, "DEMO: 2 changes merged, not live", None),
        ("release:SAMPLE", pid, "Sample app: 1 change merged, not live", None)]
    assert [r["ref"] for r in await reads.needs_you(repo, now=NOW, project_key="SAMPLE")] == ["release:SAMPLE"]


async def test_epic_rows_only_for_own_human_wait(repo):
    e = await mk_epic(repo, waiting_on="agent:a")
    await mk_task(repo, epic_id=e, summary="said done", status="done", last=NOW - 30)
    await mk_epic(repo, key="DEMO-E2", waiting_on="human:owner", last=NOW - 20)
    await repo.execute("update epics set question='Approve the spec?', answer_how='Reply:', reply_code='ok E2', "
                       "goal='Demo goal.' where key='DEMO-E2'")
    await mk_epic(repo, key="DEMO-E3", waiting_on="human:owner", last=NOW - 10)
    await mk_epic(repo, key="DEMO-E4", waiting_on="human:owner", manual="canceled", board="canceled")
    e5 = await mk_epic(repo, key="DEMO-E5", waiting_on="human:owner", confirmed=NOW - 5)
    await mk_task(repo, epic_id=e5, status="done", confirmed=NOW - 5)
    rows = await reads.needs_you(repo, now=NOW)
    assert [(r["kind"], r["ref"]) for r in rows] == [("epic", "DEMO-E2"), ("epic", "DEMO-E3"), ("task", "DEMO-1")]
    by = {r["ref"]: r for r in rows}
    assert pick(by["DEMO-E2"], *ASK) == ("decide", "Approve the spec?", "Reply:", "ok E2", False, False)
    assert by["DEMO-E2"]["context"] == "Demo goal."
    assert pick(by["DEMO-E3"], *ASK) == ("decide", "No question recorded yet.", "Ask your agent about this task:",
                                         "DEMO-E3?", True, True)


async def test_task_detail_carries_ask_and_epic_next_step(repo):
    e = await mk_epic(repo, waiting_on="agent:a")
    await repo.execute("update epics set next_step = 'Write the plan.' where id = ?", (e,))
    await mk_task(repo, epic_id=e, summary="ask", waiting_on="human:owner")
    await ask(repo, "DEMO-1", question="Go?", answer_how="Reply:", reply_code="go", ask_kind="decide",
              not_before=NOW - 5)
    d = await reads.task_detail(repo, key="DEMO-1", now=NOW)
    assert pick(d, "question", "answer_how", "reply_code", "ask_kind", "not_before", "epic_next_step") == (
        "Go?", "Reply:", "go", "decide", NOW - 5, "Write the plan.")
    assert pick(d["ask"], *ASK) == ("decide", "Go?", "Reply:", "go", False, False)
    await mk_task(repo, summary="agent work")
    d = await reads.task_detail(repo, key="DEMO-2", now=NOW)
    assert (d["ask"], d["epic_next_step"], d["question"]) == (None, None, None)
    await mk_item(repo, "owner/sample#9", None, "review", source="github", merged=NOW - 9, filing="standalone",
                  project_id=1)
    d = await reads.task_detail(repo, key="DEMO-3", now=NOW)
    assert pick(d["ask"], "ask_kind", "question", "reply_code") == (
        "release", "Release DEMO to its live branch?", "release demo")


async def test_needs_you_includes_no_epic_task_waiting_on_human(repo):
    i = await mk_item(repo, "9", None, "review", filing="standalone", waiting_on="human:owner", last=NOW - 5)
    await mk_item(repo, "10", None, "done", filing="standalone", waiting_on="human:owner")
    await mk_item(repo, "11", None, "review", filing="unfiled", waiting_on="human:owner")
    rows = await reads.needs_you(repo, now=NOW)
    tid = (await repo.first("select task_id from items where id=?", (i,)))["task_id"]
    assert [(r["kind"], r["id"], r["ref"], r["reasons"]) for r in rows] == [
        ("task", tid, "DEMO-1", ["waiting on you"])]


async def test_needs_you_lists_tasks_waiting_on_human(repo):
    e = await mk_epic(repo, waiting_on="agent:a")
    t1 = await mk_task(repo, epic_id=e, summary="sign off", waiting_on="human:owner", last=NOW - 50)
    await mk_task(repo, epic_id=e, summary="agent work", waiting_on="agent:a")
    t3 = await mk_task(repo, epic_id=e, summary="agent says done", status="done", last=NOW - 20)
    await mk_task(repo, epic_id=e, summary="dropped", status="canceled", waiting_on="human:owner")
    await mk_task(repo, epic_id=e, summary="confirmed", status="done", confirmed=1, waiting_on="human:owner")
    rows = await reads.needs_you(repo, now=NOW)
    tasks = [(r["ref"], r["title"], r["reasons"]) for r in rows if r["kind"] == "task"]
    assert tasks == [("DEMO-1", "sign off", ["waiting on you"]),
                     ("DEMO-3", "agent says done", ["awaiting your confirmation"])]
    assert {r["id"] for r in rows if r["kind"] == "task"} == {t1, t3}
    assert next(r for r in rows if r["kind"] == "task")["epic_key"] == "DEMO-E1"


async def test_needs_you_hides_tasks_of_canceled_epics(repo):
    e = await mk_epic(repo, manual="canceled", board="canceled", waiting_on="agent:a")
    await mk_task(repo, epic_id=e, summary="left behind", waiting_on="human:owner")
    live = await mk_epic(repo, "DEMO-E2", waiting_on="agent:a")
    t = await mk_task(repo, epic_id=live, summary="still open", waiting_on="human:owner")
    rows = await reads.needs_you(repo, now=NOW)
    assert [r["id"] for r in rows if r["kind"] == "task"] == [t]


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
    assert set(refs) == {"DEMO-E1", "DEMO-1", "DEMO-2"}
    assert refs["DEMO-E1"]["waiting_group"] == "human"
    assert refs["DEMO-1"]["waiting_group"] == "agent" and refs["DEMO-1"]["kind"] == "task"
    assert refs["DEMO-2"]["waiting_group"] == "source"
    assert refs["DEMO-2"]["stalled_for_hours"] == 3.0
    assert refs["DEMO-1"]["epic_key"] == "DEMO-E1" and refs["DEMO-2"]["epic_key"] is None
    assert [r["waiting_since"] for r in rows] == sorted(r["waiting_since"] for r in rows)


async def test_stalled_filter_agent_only(repo):
    await _stall_setup(repo)
    rows = await reads.stalled(repo, now=NOW, waiting_on="agent")
    assert [r["ref"] for r in rows] == ["DEMO-1"]
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
    # one task per item; the canceled one is left out; ordered by key
    assert [x["key"] for x in t] == ["DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4", "DEMO-5", "DEMO-6", "DEMO-8"]
    assert [x["status"] for x in t] == ["todo", "in_progress", "in_progress", "review", "done", "done", "todo"]
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


async def test_epic_detail_backlog_link_makes_todo_task(repo):
    e = await mk_epic(repo)
    await mk_item(repo, "1", e, "backlog")
    d = await reads.epic_detail(repo, key="DEMO-E1", now=NOW)
    assert [(t["key"], t["status"]) for t in d["tasks"]] == [("DEMO-1", "todo")]


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
    assert len(d["tasks"]) == 60 and len(d["relations"]) == 1 and len(d["events"]) == 1
    assert max(seen) <= 6  # epic ids only, never one parameter per item


async def test_stalled_skips_items_of_canceled_epic(repo):
    e = await mk_epic(repo, manual="canceled", board="canceled")
    await mk_item(repo, "1", e, "in_progress", last=NOW - 100 * H)
    await mk_item(repo, "2", None, "in_progress", filing="standalone", last=NOW - 100 * H)
    assert [r["ref"] for r in await reads.stalled(repo, now=NOW)] == ["DEMO-2"]


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
    assert sorted((r["kind"], r["ref"]) for r in rows) == [("epic", "OTHER-E1"), ("task", "OTHER-1")]
    assert await task_key(repo, i) == "OTHER-1"


async def test_stalled_project_filter_uses_item_or_epic_project(repo):
    await repo.execute("insert into sources(name, stall_hours, updated_at) values('kanban', 1, 1)")
    d = await mk_epic(repo, last=NOW - 9 * H)
    o = await mk_epic(repo, key="OTHER-E1", project="OTHER", last=NOW - 9 * H)
    await mk_item(repo, "1", d, "in_progress", last=NOW - 5 * H)
    await mk_item(repo, "2", o, "in_progress", last=NOW - 5 * H)
    await mk_item(repo, "3", None, "todo", filing="standalone", last=NOW - 5 * H,
                  project_id=await _pid(repo, "OTHER"))
    rows = await reads.stalled(repo, now=NOW, project_key="OTHER")
    assert {r["ref"] for r in rows} == {"OTHER-E1", "OTHER-1", "OTHER-2"}


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


# --- tasks ---

async def test_board_progress_counts_tasks_not_items(repo):
    e = await mk_epic(repo)
    t = await mk_task(repo, epic_id=e)
    await mk_item(repo, "1", e, "done", task_id=t)
    await mk_item(repo, "2", e, "review", merged=NOW - 9, source="github", task_id=t)
    b = await reads.board(repo, now=NOW)
    card = col(b, "review")["cards"][0]
    assert card["progress"] == {"done": 0, "total": 1}
    assert card["flags"] == ["merged_not_live"]


async def test_tasks_board_lanes_in_epic_order_then_no_epic(repo):
    e1 = await mk_epic(repo, key="DEMO-E1", title="first")
    e2 = await mk_epic(repo, key="DEMO-E2", title="second", manual="backlog")
    await mk_epic(repo, key="DEMO-E3", title="dropped", manual="canceled")
    await mk_epic(repo, key="OTHER-E1", project="OTHER")
    t1 = await mk_task(repo, epic_id=e1, summary="running")
    await mk_item(repo, "1", e1, "in_progress", task_id=t1)
    await mk_item(repo, "2", e1, "done", source="github", merged=NOW - 5, live=NOW - 1, task_id=t1)
    await mk_task(repo, epic_id=e2, summary="planned")
    await mk_task(repo, summary="loose", status="review")
    await mk_task(repo, project_id=await _pid(repo, "OTHER"), summary="elsewhere")
    b = await reads.tasks_board(repo, project_key="DEMO", now=NOW)
    assert b["project"] == "DEMO" and b["columns"] == ["todo", "in_progress", "review", "done"]
    # board order: backlog epic before in-progress epic; canceled epic left out; No epic last
    assert [ln["epic"] and ln["epic"]["key"] for ln in b["lanes"]] == ["DEMO-E2", "DEMO-E1", None]
    assert b["lanes"][1]["epic"] == {"key": "DEMO-E1", "title": "first", "progress": {"done": 0, "total": 1}}
    running = b["lanes"][1]["tasks"]["in_progress"][0]
    assert running["key"] == "DEMO-1" and running["epic_key"] == "DEMO-E1"
    assert running["links_summary"] == {"kanban": {"count": 1, "state": "running"},
                                        "github": {"count": 1, "state": "live"}}
    assert running["reason"] == "In progress: a linked item is running"
    assert set(running) >= {"id", "key", "type", "summary", "description", "done_when", "project_key",
                            "epic_key", "status", "flags", "reason", "priority", "owner", "waiting_on",
                            "waiting_since", "stalled", "refs", "reporter", "links_summary",
                            "last_activity_at"}
    assert [x["summary"] for x in b["lanes"][0]["tasks"]["todo"]] == ["planned"]
    assert [x["summary"] for x in b["lanes"][2]["tasks"]["review"]] == ["loose"]
    assert b["lanes"][2]["tasks"]["review"][0]["links_summary"] == {}


async def test_tasks_board_hides_old_done_and_canceled(repo):
    e = await mk_epic(repo)
    await mk_task(repo, epic_id=e, summary="old", status="done", confirmed=1, last=NOW - 7 * DAY - 1)
    await mk_task(repo, epic_id=e, summary="recent", status="done", confirmed=1, last=NOW - 7 * DAY)
    await mk_task(repo, epic_id=e, summary="gone", status="canceled")
    linked = await mk_task(repo, epic_id=e, summary="old task, fresh link", last=NOW - 30 * DAY)
    await mk_item(repo, "1", e, "done", last=NOW - DAY, task_id=linked)
    b = await reads.tasks_board(repo, project_key="DEMO", now=NOW)
    lane = b["lanes"][0]
    assert [x["summary"] for x in lane["tasks"]["done"]] == ["recent", "old task, fresh link"]
    assert all(x["summary"] != "gone" for c in lane["tasks"].values() for x in c)
    assert await reads.tasks_board(repo, project_key="NOPE", now=NOW) is None


async def test_task_detail_reason_and_links(repo):
    e = await mk_epic(repo)
    t = await mk_task(repo, epic_id=e, summary="ship", refs='["OPS-8001"]')
    a = await mk_item(repo, "1", e, "done", task_id=t)
    b = await mk_item(repo, "7", e, "review", merged=NOW - 5, source="github", task_id=t)
    await repo.execute("insert into events(at,actor,via,subject_type,subject_id,kind,payload) "
                       "values(5,'x','api','task',?,'task.created','{}')", (t,))
    await repo.execute("insert into events(at,actor,via,subject_type,subject_id,kind,payload) "
                       "values(6,'x','api','item',?,'item.linked','{}')", (a,))
    d = await reads.task_detail(repo, key="DEMO-1", now=NOW)
    assert d["key"] == "DEMO-1" and d["status"] == "review"
    assert d["reason"] == "Review: a linked PR is merged but not live yet"
    assert d["refs"] == ["OPS-8001"] and d["reporter"] == "tester"
    assert [(x["id"], x["ref"], x["category"]) for x in d["links"]] == [(a, "kanban:1", "done"),
                                                                       (b, "github:7", "review")]
    assert [ev["kind"] for ev in d["events"]] == ["item.linked", "task.created"]
    assert await reads.task_detail(repo, key="DEMO-9", now=NOW) is None


async def test_task_detail_merged_away_reason(repo):
    t2 = await mk_task(repo, summary="survivor")
    await mk_task(repo, summary="dup", status="canceled", merged_into=t2)
    d = await reads.task_detail(repo, key="DEMO-2", now=NOW)
    assert (d["status"], d["reason"], d["merged_into"]) == ("canceled", "Merged into DEMO-1", "DEMO-1")


async def test_stalled_lists_unstarted_planned_task_after_7_days(repo):
    e = await mk_epic(repo, last=NOW)
    await mk_task(repo, epic_id=e, summary="planned", last=NOW - 168 * H)
    assert [r["ref"] for r in await reads.stalled(repo, now=NOW) if r["kind"] == "task"] == []
    rows = [r for r in await reads.stalled(repo, now=NOW + 1) if r["kind"] == "task"]
    assert [(r["ref"], r["title"], r["stalled_for_hours"]) for r in rows] == [("DEMO-1", "planned", 168.0)]


async def test_stalled_planned_source_row_sets_threshold_for_tasks_without_links(repo):
    e = await mk_epic(repo, last=NOW)
    await mk_task(repo, epic_id=e, summary="planned", last=NOW - 48 * H)
    await repo.execute("insert into sources(name, stall_hours, updated_at) values ('planned', 48, 0)")
    assert [r["ref"] for r in await reads.stalled(repo, now=NOW) if r["kind"] == "task"] == []
    rows = [r for r in await reads.stalled(repo, now=NOW + 1) if r["kind"] == "task"]
    assert [(r["ref"], r["stalled_for_hours"]) for r in rows] == [("DEMO-1", 48.0)]


async def test_epic_with_only_a_planned_task_stalls_after_7_days(repo):
    # the epic itself is old; its only open work is a planned task (no links)
    e = await mk_epic(repo, last=NOW - 300 * H)
    await mk_task(repo, epic_id=e, summary="planned", last=NOW - 30 * H)

    def epics(rows):
        return [r["ref"] for r in rows if r["kind"] == "epic"]

    assert epics(await reads.stalled(repo, now=NOW)) == []
    assert col(await reads.board(repo, now=NOW), "todo")["cards"][0]["stalled"] is False
    later = NOW + 139 * H  # the task is 169 h old
    assert epics(await reads.stalled(repo, now=later)) == ["DEMO-E1"]
    assert col(await reads.board(repo, now=later), "todo")["cards"][0]["stalled"] is True
    assert (await reads.epic_detail(repo, key="DEMO-E1", now=later))["epic"]["stalled"] is True


async def test_epic_with_only_a_planned_task_waits_since_the_task(repo):
    # the epic was last active 200 h ago, its only open work (a planned task) 169 h ago
    e = await mk_epic(repo, last=NOW - 200 * H)
    await mk_task(repo, epic_id=e, summary="planned", last=NOW - 169 * H)
    rows = [r for r in await reads.stalled(repo, now=NOW) if r["kind"] == "epic"]
    assert [(r["ref"], r["stalled_for_hours"]) for r in rows] == [("DEMO-E1", 169.0)]
    assert rows[0]["waiting_since"] == NOW - 169 * H
    card = col(await reads.board(repo, now=NOW), "todo")["cards"][0]
    assert card["waiting_since"] == NOW - 169 * H
    # a newer done or canceled task doesn't count
    await mk_task(repo, epic_id=e, summary="dropped", status="canceled", last=NOW - H)
    card = col(await reads.board(repo, now=NOW), "todo")["cards"][0]
    assert card["waiting_since"] == NOW - 169 * H


async def test_epic_waiting_since_with_open_items_ignores_tasks(repo):
    e = await mk_epic(repo, last=NOW - 200 * H)
    await mk_task(repo, epic_id=e, summary="planned", last=NOW - H)
    await mk_item(repo, "x1", epic_id=e, last=NOW - 50 * H)
    card = col(await reads.board(repo, now=NOW), "in_progress")["cards"][0]
    assert card["waiting_since"] == NOW - 50 * H
