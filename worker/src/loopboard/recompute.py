"""Recompute and persist an epic's derived column (D1: update + event in one batch)."""
import json

from .derive import derive_epic


async def recompute_epic(repo, epic_id: int, *, actor: str, via: str, now: int) -> str:
    epic = await repo.first("select * from epics where id = ?", (epic_id,))
    items = await repo.query("select * from items where epic_id = ?", (epic_id,))
    new = derive_epic(epic, items, now).board_column
    old = epic["board_column"]
    if new == old:
        return new
    if new == "done":
        done_at = now
    elif old == "done":
        done_at = None
    else:
        done_at = epic["done_at"]
    await repo.batch([
        ("update epics set board_column = ?, done_at = ?, updated_at = ? where id = ?",
         (new, done_at, now, epic_id)),
        ("insert into events(at, actor, via, subject_type, subject_id, kind, payload) "
         "values(?, ?, ?, 'epic', ?, 'epic.column_changed', ?)",
         (now, actor, via, epic_id, json.dumps({"from": old, "to": new}))),
    ])
    return new
