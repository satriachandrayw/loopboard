from loopboard import cron
from tests.test_reads import H, NOW, mk_epic, mk_item


async def kinds(repo):
    return [r["kind"] for r in await repo.query("select kind from events order by id")]


async def test_cron_records_stall_start_once(repo):
    e = await mk_epic(repo, last=NOW - 100 * H)
    i = await mk_item(repo, "1", e, "in_progress", last=NOW - 30 * H)
    assert await cron.run_stall_transitions(repo, now=NOW) == {"started": 2, "cleared": 0}
    assert await cron.run_stall_transitions(repo, now=NOW + 60) == {"started": 0, "cleared": 0}
    assert (await repo.first("select stalled_since from items where id=?", (i,)))["stalled_since"] == NOW
    ev = await repo.query("select * from events where kind='stall.started'")
    assert len(ev) == 2 and all(r["actor"] == "cron" and r["via"] == "cron" for r in ev)


async def test_cron_records_stall_clear(repo):
    e = await mk_epic(repo)
    i = await mk_item(repo, "1", e, "in_progress", last=NOW - 30 * H)
    await cron.run_stall_transitions(repo, now=NOW)
    await repo.execute("update items set last_activity_at=? where id=?", (NOW + 5, i))
    assert await cron.run_stall_transitions(repo, now=NOW + 10) == {"started": 0, "cleared": 2}
    assert (await repo.first("select stalled_since from items where id=?", (i,)))["stalled_since"] is None
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
