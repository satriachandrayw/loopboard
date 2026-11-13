"""Stall transitions (cron): record stall.started / stall.cleared and stalled_since for epics and tasks."""
import json

from .reads import _derive, load_epics, load_tasks, thresholds
from .stall import epic_stalled, task_stalled

CHUNK = 40
EVENT = ("insert into events(at, actor, via, subject_type, subject_id, kind, payload) "
         "values(?, 'cron', 'cron', ?, ?, ?, ?)")


async def run_stall_transitions(repo, *, now: int) -> dict:
    th = await thresholds(repo)
    changes = []  # (table, subject_type, id, start?)

    def check(table, stype, row, is_stalled):
        since = row["stalled_since"]
        if is_stalled and since is None:
            changes.append((table, stype, row["id"], True))
        elif not is_stalled and since is not None:
            changes.append((table, stype, row["id"], False))

    canceled = set()
    for row in await load_epics(repo):
        e = row["epic"]
        if e["manual_column"] == "canceled":
            canceled.add(e["id"])
        check("epics", "epic", e, epic_stalled(e, row["items"], row["tasks"], _derive(row, now), now, th))
    for row in await load_tasks(repo):
        t = row["task"]
        check("tasks", "task", t,
              t["epic_id"] not in canceled and task_stalled(t, row["items"], row["derived"], now, th))
    # Items no longer stall on their own (tasks do); clear any item stall left from before tasks.
    for i in await repo.query("select id, stalled_since from items where stalled_since is not null"):
        check("items", "item", i, False)

    started = cleared = 0
    for n in range(0, len(changes), CHUNK):
        stmts = []
        for table, stype, id_, start in changes[n:n + CHUNK]:
            stmts.append((f"update {table} set stalled_since = ? where id = ?",
                          (now if start else None, id_)))
            stmts.append((EVENT, (now, stype, id_, "stall.started" if start else "stall.cleared",
                                  json.dumps({"stalled_since": now if start else None}))))
        await repo.batch(stmts)
    for *_, start in changes:
        started += start
        cleared += not start
    return {"started": started, "cleared": cleared}
