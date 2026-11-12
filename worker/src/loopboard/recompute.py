"""Recompute and persist an epic's derived column (D1: update + event in one batch)."""
import json

from .derive import derive_epic

IN_CHUNK = 99  # D1 allows 100 bound parameters per statement


def chunks(seq, n=IN_CHUNK):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _qs(n: int) -> str:
    return ", ".join("?" * n)


async def recompute_epics(repo, epic_ids, *, actor: str, via: str, now: int) -> dict[int, str]:
    """Recompute many epics with a bounded number of D1 calls:
    one epics select and one items select per 99 ids, and one write batch."""
    ids = sorted(set(epic_ids))
    if not ids:
        return {}
    epics, by_epic = {}, {i: [] for i in ids}
    for part in chunks(ids):
        for e in await repo.query(f"select * from epics where id in ({_qs(len(part))})", part):
            epics[e["id"]] = e
        for it in await repo.query(
                f"select * from items where filing = 'epic' and epic_id in ({_qs(len(part))})", part):
            by_epic[it["epic_id"]].append(it)
    out, stmts = {}, []
    for eid in ids:
        epic = epics.get(eid)
        if epic is None:
            continue
        new = derive_epic(epic, by_epic[eid], now).board_column
        old = epic["board_column"]
        out[eid] = new
        if new == old:
            continue
        if new == "done":
            done_at = now
        elif old == "done":
            done_at = None
        else:
            done_at = epic["done_at"]
        stmts += [
            ("update epics set board_column = ?, done_at = ?, updated_at = ? where id = ?",
             (new, done_at, now, eid)),
            ("insert into events(at, actor, via, subject_type, subject_id, kind, payload) "
             "values(?, ?, ?, 'epic', ?, 'epic.column_changed', ?)",
             (now, actor, via, eid, json.dumps({"from": old, "to": new}))),
        ]
    if stmts:
        await repo.batch(stmts)
    return out


async def recompute_epic(repo, epic_id: int, *, actor: str, via: str, now: int) -> str:
    out = await recompute_epics(repo, [epic_id], actor=actor, via=via, now=now)
    if epic_id not in out:
        raise LookupError(f"epic {epic_id} not found")
    return out[epic_id]
