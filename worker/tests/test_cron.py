from loopboard import cron
from tests.test_reads import H, NOW, mk_epic, mk_item, mk_task


async def kinds(repo):
    return [r["kind"] for r in await repo.query("select kind from events order by id")]


async def test_cron_records_stall_start_once(repo):
    e = await mk_epic(repo, last=NOW - 100 * H)
    i = await mk_item(repo, "1", e, "in_progress", last=NOW - 30 * H)
    assert await cron.run_stall_transitions(repo, now=NOW) == {"started": 2, "cleared": 0}
    assert await cron.run_stall_transitions(repo, now=NOW + 60) == {"started": 0, "cleared": 0}
    tid = (await repo.first("select task_id from items where id=?", (i,)))["task_id"]
    assert (await repo.first("select stalled_since from tasks where id=?", (tid,)))["stalled_since"] == NOW
    ev = await repo.query("select * from events where kind='stall.started'")
    assert sorted(r["subject_type"] for r in ev) == ["epic", "task"]
    assert len(ev) == 2 and all(r["actor"] == "cron" and r["via"] == "cron" for r in ev)


async def test_cron_records_stall_clear(repo):
    e = await mk_epic(repo)
    i = await mk_item(repo, "1", e, "in_progress", last=NOW - 30 * H)
    await cron.run_stall_transitions(repo, now=NOW)
    await repo.execute("update items set last_activity_at=? where id=?", (NOW + 5, i))
    assert await cron.run_stall_transitions(repo, now=NOW + 10) == {"started": 0, "cleared": 2}
    assert (await repo.first("select t.stalled_since from tasks t join items i on i.task_id = t.id "
                             "where i.id=?", (i,)))["stalled_since"] is None
    assert "stall.cleared" in await kinds(repo)


async def test_cron_ignores_done_items(repo):
    e = await mk_epic(repo, confirmed=1)
    await mk_item(repo, "1", e, "done", waiting_on=None, last=NOW - 100 * H)
    await mk_item(repo, "2", None, "canceled", waiting_on=None, last=NOW - 100 * H)
    await mk_item(repo, "3", None, "todo", filing="ignored", last=NOW - 100 * H)
    assert await cron.run_stall_transitions(repo, now=NOW) == {"started": 0, "cleared": 0}
    assert await kinds(repo) == []


async def test_cron_skips_unfiled_items(repo):
    await mk_item(repo, "1", None, "todo", filing="unfiled", last=NOW - 100 * H)
    assert await cron.run_stall_transitions(repo, now=NOW) == {"started": 0, "cleared": 0}
    assert await kinds(repo) == []


async def test_cron_skips_tasks_of_canceled_epic_and_clears_stalled(repo):
    e = await mk_epic(repo, manual="canceled", board="canceled")
    i = await mk_item(repo, "1", e, "in_progress", last=NOW - 100 * H)
    assert await cron.run_stall_transitions(repo, now=NOW) == {"started": 0, "cleared": 0}
    await repo.execute("update tasks set stalled_since=?", (NOW - H,))
    assert await cron.run_stall_transitions(repo, now=NOW) == {"started": 0, "cleared": 1}
    assert (await repo.first("select stalled_since from tasks"))["stalled_since"] is None
    # an item stall left from before tasks is cleared once
    await repo.execute("update items set stalled_since=? where id=?", (NOW - H, i))
    assert await cron.run_stall_transitions(repo, now=NOW) == {"started": 0, "cleared": 1}
    assert (await repo.first("select stalled_since from items where id=?", (i,)))["stalled_since"] is None


async def test_cron_stall_transitions_for_tasks(repo):
    e = await mk_epic(repo, last=NOW)
    t = await mk_task(repo, epic_id=e, summary="planned", last=NOW - 169 * H)
    assert await cron.run_stall_transitions(repo, now=NOW) == {"started": 1, "cleared": 0}
    ev = await repo.query("select * from events where kind='stall.started'")
    assert [(r["subject_type"], r["subject_id"]) for r in ev] == [("task", t)]
    await repo.execute("update tasks set last_activity_at=? where id=?", (NOW, t))
    assert await cron.run_stall_transitions(repo, now=NOW + 1) == {"started": 0, "cleared": 1}


async def test_cron_epic_with_only_a_planned_task_uses_planned_threshold(repo):
    e = await mk_epic(repo, last=NOW - 300 * H)
    await mk_task(repo, epic_id=e, summary="planned", last=NOW - 30 * H)
    assert await cron.run_stall_transitions(repo, now=NOW) == {"started": 0, "cleared": 0}
    assert await cron.run_stall_transitions(repo, now=NOW + 139 * H) == {"started": 2, "cleared": 0}
    ev = await repo.query("select subject_type from events where kind='stall.started'")
    assert sorted(r["subject_type"] for r in ev) == ["epic", "task"]
