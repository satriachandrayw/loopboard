"""Idempotent item upsert (D1, D11, D12, D13)."""
import json

from .model import ItemIn, ValidationError, parse_ts
from .recompute import recompute_epic

PLAIN = ("title", "url", "status_category", "raw_status", "owner", "waiting_on",
         "blocked_reason", "next_step")
STORED = PLAIN + ("last_activity_at", "merged_at", "live_at", "project_id", "epic_id", "filing")


async def ingest_items(repo, *, source: str, items: list[ItemIn], actor: str, via: str, now: int) -> dict:
    # Resolve every referenced epic/project before any write.
    epics, projects = {}, {}
    for it in items:
        if it.epic_key and it.epic_key not in epics:
            row = await repo.first("select id, project_id from epics where key = ?", (it.epic_key,))
            if row is None:
                raise ValidationError(f"unknown epic_key {it.epic_key}")
            epics[it.epic_key] = row
        if it.project_key and it.project_key not in projects:
            row = await repo.first("select id from projects where key = ?", (it.project_key,))
            if row is None:
                raise ValidationError(f"unknown project_key {it.project_key}")
            projects[it.project_key] = row["id"]

    out = {"accepted": len(items), "created": 0, "updated": 0, "skipped_older": 0}
    touched: set[int] = set()
    for it in items:
        ts = parse_ts(it.last_activity_at)
        stored = await repo.first(
            "select * from items where source = ? and external_id = ?", (source, it.external_id))
        if stored is not None and stored["last_activity_at"] > ts:
            out["skipped_older"] += 1
            continue
        given = it.model_fields_set
        new = {k: getattr(it, k) for k in PLAIN if k in given}
        new["last_activity_at"] = ts
        for k in ("merged_at", "live_at"):
            if getattr(it, k) is not None:
                new[k] = parse_ts(getattr(it, k))
        if it.project_key:
            new["project_id"] = projects[it.project_key]
        if it.epic_key:
            e = epics[it.epic_key]
            new.update(project_id=e["project_id"], epic_id=e["id"], filing="epic")

        if stored is None:
            new.setdefault("filing", "unfiled")
            new["epic_id"] = new.get("epic_id")
            payload = {"source": source, "external_id": it.external_id, **new}
            cols = ["source", "external_id", "created_at", "updated_at", *new]
            vals = [source, it.external_id, now, now, *new.values()]
            await repo.batch([
                (f"insert into items({', '.join(cols)}) values ({', '.join('?' * len(cols))})", vals),
                ("insert into events(at, actor, via, subject_type, subject_id, kind, payload) "
                 "select ?, ?, ?, 'item', id, 'item.created', ? from items "
                 "where source = ? and external_id = ?",
                 (now, actor, via, json.dumps(payload), source, it.external_id)),
            ])
            out["created"] += 1
            if new.get("epic_id"):
                touched.add(new["epic_id"])
            continue

        changed = {k: v for k, v in new.items() if stored[k] != v}
        if not changed:
            continue
        sets = ", ".join(f"{k} = ?" for k in changed)
        await repo.batch([
            (f"update items set {sets}, updated_at = ? where id = ?", [*changed.values(), now, stored["id"]]),
            ("insert into events(at, actor, via, subject_type, subject_id, kind, payload) "
             "values(?, ?, ?, 'item', ?, 'item.updated', ?)",
             (now, actor, via, stored["id"], json.dumps(changed))),
        ])
        out["updated"] += 1
        for eid in (stored["epic_id"], changed.get("epic_id")):
            if eid:
                touched.add(eid)

    for eid in sorted(touched):
        await recompute_epic(repo, eid, actor=actor, via=via, now=now)
    return out
