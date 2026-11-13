"""Idempotent item upsert (D1, D11, D12, D13) and linking to tasks (tasks design).

Bounded D1 calls per request (Free plan allows ~50 queries per invocation):
stored rows, epics, projects, tasks by key, refs of open tasks and the task counters are loaded
with `in (...)` selects (99 ids per select), every insert/update/event goes into one batch, and
touched epics are recomputed with recompute_epics.

A new or unfiled item is linked, in this order, to the task its `task_key` names (a merged-away
task resolves to its survivor), to the open task of its project whose ref appears in its title as
a whole token, or to a new task made under the epic its `epic_key` names. Unknown keys are counted,
never an error.
"""
import json
import re

from .model import MERGE_DEPTH, ItemIn, ValidationError, parse_ts
from .recompute import _qs, chunks, recompute_epics
from .writes import auto_task_stmts

PLAIN = ("title", "url", "status_category", "raw_status", "owner", "waiting_on",
         "blocked_reason", "next_step")
STORED = PLAIN + ("last_activity_at", "merged_at", "live_at", "project_id", "epic_id", "filing", "task_id")
EVENT = "insert into events(at, actor, via, subject_type, subject_id, kind, payload) "
MAX_FUTURE_SECONDS = 3600
ITEM_ID = "(select id from items where source = ? and external_id = ?)"


async def _by_key(repo, sql: str, keys) -> dict:
    out = {}
    for part in chunks(sorted(keys)):
        for r in await repo.query(sql.format(_qs(len(part))), part):
            out[r["key"]] = r
    return out


RACES = ("UNIQUE constraint failed: items.source, items.external_id",
         "UNIQUE constraint failed: tasks.project_id, tasks.seq", "UNIQUE constraint failed: tasks.key")


def _lost_create_race(e: Exception) -> bool:
    """A concurrent ingest (or task create) took one of our item or task keys first. sqlite3 raises
    IntegrityError and D1 a JS exception, both with these messages."""
    return any(r in str(e) for r in RACES)


def _ref_pattern(ref: str):
    return re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(ref)}(?![A-Za-z0-9_-])")


async def _tasks_by_key(repo, keys) -> dict:
    """Open tasks by key; a merged-away key maps to its survivor. Merges are followed for the whole
    set at once: one chunked `id in (...)` select per hop, at most MERGE_DEPTH hops."""
    cols = "select id, key, project_id, epic_id, status, merged_into from tasks"
    found = await _by_key(repo, cols + " where key in ({})", keys)
    by_id = {t["id"]: t for t in found.values()}
    merged = lambda t: t["status"] == "canceled" and t["merged_into"]  # noqa: E731
    for _ in range(MERGE_DEPTH):
        want = {t["merged_into"] for t in list(by_id.values()) if merged(t)} - by_id.keys()
        if not want:
            break
        for part in chunks(sorted(want)):
            for r in await repo.query(cols + f" where id in ({_qs(len(part))})", part):
                by_id[r["id"]] = r
    out = {}
    for k, t in found.items():
        hops = 0
        while t is not None and merged(t) and hops < MERGE_DEPTH:
            t = by_id.get(t["merged_into"])
            hops += 1
        if t is not None and t["status"] != "canceled":
            out[k] = t
    return out


async def _refs_and_seqs(repo, project_ids) -> tuple[dict[int, list], dict[int, int]]:
    """One select per 49 projects: per project (pattern, task) for each ref of its open tasks
    (oldest task first), and the highest task seq."""
    refs: dict[int, list] = {}
    seqs: dict[int, int] = {}
    for part in chunks(sorted(project_ids), 49):
        q = _qs(len(part))
        for r in await repo.query(
                "select 'seq' as kind, project_id, max(seq) as m, null as id, null as key, null as epic_id, "
                f"null as refs from tasks where project_id in ({q}) group by project_id "
                "union all select 'ref', project_id, null, id, key, epic_id, refs from tasks "
                f"where status != 'canceled' and refs != '[]' and project_id in ({q}) order by id",
                [*part, *part]):
            if r["kind"] == "seq":
                seqs[r["project_id"]] = r["m"] or 0
            else:
                for ref in json.loads(r["refs"]):
                    refs.setdefault(r["project_id"], []).append((_ref_pattern(ref), r))
    return refs, seqs


async def ingest_items(repo, *, source: str, items: list[ItemIn], actor: str, via: str, now: int) -> dict:
    """Upsert items. The write batch is one transaction, so a lost create race rolls everything
    back; it is retried once, re-reading state, so the raced item goes through the update path."""
    try:
        return await _ingest_once(repo, source=source, items=items, actor=actor, via=via, now=now)
    except Exception as e:
        if not _lost_create_race(e):
            raise
    return await _ingest_once(repo, source=source, items=items, actor=actor, via=via, now=now)


async def _ingest_once(repo, *, source: str, items: list[ItemIn], actor: str, via: str, now: int) -> dict:
    # Reject far-future timestamps up front: nothing is written for the request.
    for it in items:
        for name in ("last_activity_at", "merged_at", "live_at"):
            v = getattr(it, name)
            if v is not None and parse_ts(v) > now + MAX_FUTURE_SECONDS:
                raise ValidationError(f"{name} is more than 1 hour in the future (item {it.external_id})")
    # Resolve every referenced epic/project before any write. An unknown or canceled epic is not an
    # error (v1a.4): the item is ingested as if it had no epic_key and counted in unknown_epic.
    epic_keys = {it.epic_key for it in items if it.epic_key}
    project_keys = {it.project_key for it in items if it.project_key}
    epics = {k: e for k, e in (await _by_key(
        repo, "select id, project_id, key, manual_column from epics where key in ({})", epic_keys)).items()
        if e["manual_column"] != "canceled"}
    projects = await _by_key(repo, "select id, key from projects where key in ({})", project_keys)
    for k in sorted(project_keys - projects.keys()):
        raise ValidationError(f"unknown project_key {k}")
    task_keys = {it.task_key for it in items if it.task_key}
    tasks = await _tasks_by_key(repo, task_keys) if task_keys else {}

    # Current state per external_id; updated in memory as the batch is applied in order.
    state: dict[str, dict | None] = {}
    for part in chunks(sorted({it.external_id for it in items})):
        for r in await repo.query(
                f"select * from items where source = ? and external_id in ({_qs(len(part))})",
                [source, *part]):
            state[r["external_id"]] = r

    # Refs are matched within the item's project; load them once for every project in the batch.
    ref_projects = {p["id"] for p in projects.values()} | {e["project_id"] for e in epics.values()} | {
        r["project_id"] for r in state.values() if r["project_id"] and r["filing"] == "unfiled"}
    refs, seqs = await _refs_and_seqs(repo, ref_projects) if ref_projects else ({}, {})
    epic_keys_by_id = {e["id"]: k for k, e in epics.items()}

    out = {"accepted": len(items), "created": 0, "updated": 0, "skipped_older": 0,
           "unknown_epic": sum(1 for it in items if it.epic_key and it.epic_key not in epics),
           "linked_task": 0, "auto_tasks": 0,
           "unknown_task": sum(1 for it in items if it.task_key and it.task_key not in tasks)}
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
        # A tag or ref files only a new or unfiled item; an epic, standalone or ignored filing (set
        # by a human or Hermes) is never overwritten by one.
        eligible = stored is None or stored["filing"] == "unfiled"
        keeps_project = stored is not None and stored["filing"] in ("epic", "standalone")
        if it.project_key and not keeps_project:
            new["project_id"] = projects[it.project_key]["id"]
        project_id = new.get("project_id", stored and stored["project_id"])
        task = tasks.get(it.task_key) if eligible else None
        if task is None and eligible and project_id in refs:
            task = next((t for pat, t in refs[project_id] if pat.search(it.title)), None)
        epic = epics.get(it.epic_key) if eligible and task is None else None
        pre: list = []  # auto-task statements, before the item's own
        post: list = []  # statements after the item's (and its events)
        task_key = None
        if task is not None:
            task_key = task["key"]
            new.update(task_id=task["id"], project_id=task["project_id"], epic_id=task["epic_id"],
                       filing="epic" if task["epic_id"] else "standalone")
            out["linked_task"] += 1
        elif epic is not None:
            pid = epic["project_id"]
            seqs[pid] = seqs.get(pid, 0) + 1
            task_key = f"{epic_keys_by_id[epic['id']].rsplit('-E', 1)[0]}-{seqs[pid]}"
            src = {"source": source, "external_id": it.external_id, "title": it.title, "url": it.url,
                   "owner": it.owner, "waiting_on": it.waiting_on}
            pre = auto_task_stmts(src, project_id=pid, epic_id=epic["id"], seq=seqs[pid], key=task_key,
                                  actor=actor, now=now, via=via)
            new.update(project_id=pid, epic_id=epic["id"], filing="epic")
            post = [
                ("update items set task_id = (select id from tasks where key = ?) where source = ? "
                 "and external_id = ? and last_activity_at <= ?", (task_key, source, it.external_id, ts)),
                ("update tasks set origin_item_id = (select id from items where source = ? and external_id = ?) "
                 "where key = ? and origin_item_id is null", (source, it.external_id, task_key)),
            ]
            out["auto_tasks"] += 1
        linked = task is not None or epic is not None

        if stored is None:
            new.setdefault("filing", "unfiled")
            new["epic_id"] = new.get("epic_id")
            payload = {"source": source, "external_id": it.external_id, **new,
                       **({"task_key": task_key} if task_key else {})}
            cols = ["source", "external_id", "created_at", "updated_at", *new]
            vals = [source, it.external_id, now, now, *new.values()]
            stmts += [
                *pre,
                (f"insert into items({', '.join(cols)}) values ({_qs(len(cols))})", vals),
                (EVENT + f"values(?, ?, ?, 'item', {ITEM_ID}, 'item.created', ?)",
                 (now, actor, via, source, it.external_id, json.dumps(payload))),
                *post,
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
        # Filing by tag, key or ref gets its own item.filed event; the other changes go in item.updated.
        filed = {k: changed[k] for k in ("filing", "epic_id", "project_id", "task_id") if k in changed} \
            if linked else {}
        if filed and task_key:
            filed["task_key"] = task_key
        stmts += pre
        events = [(kind, payload) for kind, payload in (
            ("item.updated", {k: v for k, v in changed.items() if k not in filed}), ("item.filed", filed))
            if payload]
        # Conditional on the stored timestamp not having advanced since we read it; the events
        # are only written when that update changed a row (changes() is per connection, so it
        # reflects the statement right above it in the same batch: the update, then the first
        # event insert, which inserted a row only if the update changed one).
        guarded.append(len(stmts))
        stmts.append(
            (f"update items set {sets}, updated_at = ? where source = ? and external_id = ? "
             "and last_activity_at <= ?",
             [*changed.values(), now, source, it.external_id, ts]))
        stmts += [
            (EVENT + f"select ?, ?, ?, 'item', id, '{kind}', ? from items "
             "where source = ? and external_id = ? and changes() > 0",
             (now, actor, via, json.dumps(payload), source, it.external_id))
            for kind, payload in events]
        stmts += post
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
