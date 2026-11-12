"""Idempotent item upsert (D1, D11, D12, D13).

Bounded D1 calls per request (Free plan allows ~50 queries per invocation):
stored rows, epics and projects are loaded with `in (...)` selects (99 ids per
select), every insert/update/event goes into one batch, and touched epics are
recomputed with recompute_epics.
"""
import json

from .model import ItemIn, ValidationError, parse_ts
from .recompute import _qs, chunks, recompute_epics

PLAIN = ("title", "url", "status_category", "raw_status", "owner", "waiting_on",
         "blocked_reason", "next_step")
STORED = PLAIN + ("last_activity_at", "merged_at", "live_at", "project_id", "epic_id", "filing")
EVENT = "insert into events(at, actor, via, subject_type, subject_id, kind, payload) "
ITEM_ID = "(select id from items where source = ? and external_id = ?)"


async def _by_key(repo, sql: str, keys) -> dict:
    out = {}
    for part in chunks(sorted(keys)):
        for r in await repo.query(sql.format(_qs(len(part))), part):
            out[r["key"]] = r
    return out


async def ingest_items(repo, *, source: str, items: list[ItemIn], actor: str, via: str, now: int) -> dict:
    # Resolve every referenced epic/project before any write.
    epic_keys = {it.epic_key for it in items if it.epic_key}
    project_keys = {it.project_key for it in items if it.project_key}
    epics = await _by_key(repo, "select id, project_id, key from epics where key in ({})", epic_keys)
    projects = await _by_key(repo, "select id, key from projects where key in ({})", project_keys)
    for k in sorted(epic_keys - epics.keys()):
        raise ValidationError(f"unknown epic_key {k}")
    for k in sorted(project_keys - projects.keys()):
        raise ValidationError(f"unknown project_key {k}")

    # Current state per external_id; updated in memory as the batch is applied in order.
    state: dict[str, dict | None] = {}
    for part in chunks(sorted({it.external_id for it in items})):
        for r in await repo.query(
                f"select * from items where source = ? and external_id in ({_qs(len(part))})",
                [source, *part]):
            state[r["external_id"]] = r

    out = {"accepted": len(items), "created": 0, "updated": 0, "skipped_older": 0}
    touched: set[int] = set()
    stmts: list = []
    guarded: list[int] = []  # indexes of conditional update statements in stmts
    for it in items:
        ts = parse_ts(it.last_activity_at)
        stored = state.get(it.external_id)
        if stored is not None and stored["last_activity_at"] > ts:
            out["skipped_older"] += 1
            continue
        given = it.model_fields_set
        new = {k: getattr(it, k) for k in PLAIN if k in given}
        new["last_activity_at"] = ts
        for k in ("merged_at", "live_at"):
            if getattr(it, k) is not None:
                new[k] = parse_ts(getattr(it, k))
        keeps_project = (stored is not None and stored["filing"] in ("epic", "standalone")
                         and not it.epic_key)
        if it.project_key and not keeps_project:
            new["project_id"] = projects[it.project_key]["id"]
        if it.epic_key:
            e = epics[it.epic_key]
            new.update(project_id=e["project_id"], epic_id=e["id"], filing="epic")

        if stored is None:
            new.setdefault("filing", "unfiled")
            new["epic_id"] = new.get("epic_id")
            payload = {"source": source, "external_id": it.external_id, **new}
            cols = ["source", "external_id", "created_at", "updated_at", *new]
            vals = [source, it.external_id, now, now, *new.values()]
            stmts += [
                (f"insert into items({', '.join(cols)}) values ({_qs(len(cols))})", vals),
                (EVENT + f"values(?, ?, ?, 'item', {ITEM_ID}, 'item.created', ?)",
                 (now, actor, via, source, it.external_id, json.dumps(payload))),
            ]
            state[it.external_id] = {**{k: None for k in STORED}, **new}
            out["created"] += 1
            if new.get("epic_id"):
                touched.add(new["epic_id"])
            continue

        changed = {k: v for k, v in new.items() if stored[k] != v}
        if not changed:
            continue
        sets = ", ".join(f"{k} = ?" for k in changed)
        # Conditional on the stored timestamp not having advanced since we read it; the event
        # is only written when that update changed a row (changes() is per connection, so it
        # reflects the update right above it in the same batch).
        guarded.append(len(stmts))
        stmts += [
            (f"update items set {sets}, updated_at = ? where source = ? and external_id = ? "
             "and last_activity_at <= ?",
             [*changed.values(), now, source, it.external_id, ts]),
            (EVENT + "select ?, ?, ?, 'item', id, 'item.updated', ? from items "
             "where source = ? and external_id = ? and changes() > 0",
             (now, actor, via, json.dumps(changed), source, it.external_id)),
        ]
        state[it.external_id] = {**stored, **changed}
        out["updated"] += 1
        for eid in (stored["epic_id"], changed.get("epic_id")):
            if eid:
                touched.add(eid)

    if stmts:
        changes = await repo.batch(stmts)
        for i in guarded:
            if i < len(changes) and changes[i] == 0:
                out["updated"] -= 1
                out["skipped_older"] += 1
    await recompute_epics(repo, touched, actor=actor, via=via, now=now)
    return out
