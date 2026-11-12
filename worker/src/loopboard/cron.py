"""Stall transitions (cron): record stall.started / stall.cleared and stalled_since."""
import json

from .derive import derive_epic
from .reads import load_epics, thresholds
from .stall import epic_stalled, item_stalled

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

    for row in await load_epics(repo):
        e, items = row["epic"], row["items"]
        check("epics", "epic", e, epic_stalled(e, items, derive_epic(e, items, now), now, th))
    for i in await repo.query("select * from items where filing != 'ignored' "
                              "or stalled_since is not null"):
        check("items", "item", i, item_stalled(i, now, th))

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
