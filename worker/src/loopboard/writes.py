"""Write API logic (D1: state change + event in one batch)."""
import json

from .model import EpicIn, EpicPatch, FilingIn, RelationIn, TaskIn, TaskPatch, ValidationError
from .recompute import recompute_epic, recompute_epics

EVENT = ("insert into events(at, actor, via, subject_type, subject_id, kind, payload) "
         "values(?, ?, 'api', ?, ?, ?, ?)")
EVENT_BY_SQL = ("insert into events(at, actor, via, subject_type, subject_id, kind, payload) "
                "select ?, ?, 'api', ?, id, ?, ? from {table} where {where}")
EPIC_FIELDS = ("title", "goal", "stage", "owner", "next_step", "waiting_on", "home_url", "spec_url",
               "plan_url", "manual_column")
NOT_NULL = ("title", "goal", "stage", "manual_column")


class NotFound(LookupError):
    pass


class Conflict(Exception):
    pass


class Forbidden(Exception):
    pass


def _ev(now, actor, stype, sid, kind, payload):
    return (EVENT, (now, actor, stype, sid, kind, json.dumps(payload)))


async def _batch(repo, stmts, what):
    """repo.batch, mapping a UNIQUE violation (lost race) to Conflict. sqlite3 raises IntegrityError and
    D1 a JS exception, both with "UNIQUE constraint failed" in the message; other errors propagate."""
    try:
        return await repo.batch(stmts)
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            raise Conflict(what) from e
        raise


async def _one(repo, sql, args, what):
    row = await repo.first(sql, args)
    if row is None:
        raise NotFound(what)
    return row


async def _project(repo, key):
    return await _one(repo, "select * from projects where key = ?", (key,), f"project {key} not found")


async def _epic(repo, key):
    return await _one(repo, "select * from epics where key = ?", (key,), f"epic {key} not found")


async def create_project(repo, *, key, name, actor, now):
    if await repo.first("select id from projects where key = ?", (key,)):
        raise Conflict(f"project {key} exists")
    await _batch(repo, [
        ("insert into projects(key, name, created_at) values (?, ?, ?)", (key, name, now)),
        (EVENT_BY_SQL.format(table="projects", where="key = ?"),
         (now, actor, "project", "project.created", json.dumps({"key": key, "name": name}), key)),
    ], f"project {key} exists")
    return await _project(repo, key)


async def create_epic(repo, *, project_key, body: EpicIn, actor, now):
    project = await _project(repo, project_key)
    row = await repo.first("select max(seq) as m from epics where project_id = ?", (project["id"],))
    seq = (row["m"] or 0) + 1
    key = f"{project_key}-E{seq}"
    fields = body.model_dump()
    payload = {"key": key, "project_id": project["id"], **fields}
    cols = ["project_id", "seq", "key", *fields, "board_column", "last_activity_at", "created_at", "updated_at"]
    vals = [project["id"], seq, key, *fields.values(), fields["manual_column"], now, now, now]
    await _batch(repo, [
        (f"insert into epics({', '.join(cols)}) values ({', '.join('?' * len(cols))})", vals),
        (EVENT_BY_SQL.format(table="epics", where="key = ?"),
         (now, actor, "epic", "epic.created", json.dumps(payload), key)),
    ], f"epic {key} exists")
    epic = await _epic(repo, key)
    await recompute_epic(repo, epic["id"], actor=actor, via="api", now=now)
    return await _epic(repo, key)


async def patch_epic(repo, *, key, changes: EpicPatch, actor, now):
    given = {k: getattr(changes, k) for k in changes.model_fields_set}
    if not given:
        raise ValidationError("empty patch")
    for k in NOT_NULL:
        if k in given and given[k] is None:
            raise ValidationError(f"{k} cannot be null")
    epic = await _epic(repo, key)
    after = {**epic, **given}
    if after["manual_column"] != "canceled" and not after["waiting_on"] and (
            "waiting_on" in given or epic["manual_column"] == "canceled"):
        raise ValidationError("waiting_on is required unless the epic is canceled")
    changed = {k: v for k, v in given.items() if epic[k] != v}
    if changed:
        sets = ", ".join(f"{k} = ?" for k in changed)
        await repo.batch([
            (f"update epics set {sets}, last_activity_at = ?, updated_at = ? where id = ?",
             [*changed.values(), now, now, epic["id"]]),
            _ev(now, actor, "epic", epic["id"], "epic.updated", changed),
        ])
        await recompute_epic(repo, epic["id"], actor=actor, via="api", now=now)
    return await _epic(repo, key)


async def confirm_done(repo, *, key, actor, now):
    epic = await _epic(repo, key)
    await repo.batch([
        ("update epics set done_confirmed_at = ?, last_activity_at = ?, updated_at = ? where id = ?",
         (now, now, now, epic["id"])),
        _ev(now, actor, "epic", epic["id"], "epic.confirmed_done", {"done_confirmed_at": now}),
    ])
    await recompute_epic(repo, epic["id"], actor=actor, via="api", now=now)
    return await _epic(repo, key)


async def set_filing(repo, *, item_id, body: FilingIn, actor, now):
    """epic/standalone keep the tasks invariant: the item's task moves (same project) or an
    auto-task is made for it; ignored unlinks it."""
    item = await _item(repo, item_id)
    if body.filing == "ignored":
        return await unlink_item(repo, item_id=item_id, actor=actor, now=now, filing="ignored")
    if body.filing == "epic":
        if not body.epic_key:
            raise ValidationError("epic_key is required to file under an epic")
        epic = await _epic(repo, body.epic_key)
        project_id, epic_id = epic["project_id"], epic["id"]
    else:
        project_id = (await _project(repo, body.project_key))["id"] if body.project_key else item["project_id"]
        if not project_id:
            raise ValidationError("standalone needs a project (project_key or the item's project)")
        epic_id = None
    task = await repo.first("select * from tasks where id = ?", (item["task_id"],)) if item["task_id"] else None
    if task is not None and task["project_id"] == project_id and task["status"] != "canceled":
        if task["epic_id"] != epic_id:
            await _move_task(repo, task, epic_id, actor=actor, now=now)
        return await _item(repo, item_id)
    seq = await _next_seq(repo, project_id)
    key = f"{await _project_key(repo, project_id)}-{seq}"
    stmts = auto_task_stmts(item, project_id=project_id, epic_id=epic_id, seq=seq, key=key, actor=actor, now=now)
    stmts += _link_stmts(item, task_sql=TASK_BY_KEY, task_args=(key,), epic_id=epic_id, project_id=project_id,
                         actor=actor, now=now, payload={"task_key": key, "filing": body.filing})
    await _batch(repo, stmts, f"task {key} exists")
    await recompute_epics(repo, {item["epic_id"], epic_id} - {None}, actor=actor, via="api", now=now)
    return await _item(repo, item_id)


async def mark_deployed(repo, *, item_id, live_at: int, actor, now):
    if live_at > now + 3600:
        raise ValidationError("live_at is more than 1 hour in the future")
    item = await _one(repo, "select * from items where id = ?", (item_id,), f"item {item_id} not found")
    if item["merged_at"] is None:
        raise ValidationError("item has no merged PR")
    stmts = [
        ("update items set live_at = ?, updated_at = ? where id = ?", (live_at, now, item_id)),
        _ev(now, actor, "item", item_id, "item.deployed", {"live_at": live_at}),
    ]
    if item["epic_id"]:
        stmts.append(("update epics set last_activity_at = ?, updated_at = ? where id = ?",
                      (now, now, item["epic_id"])))
    await repo.batch(stmts)
    if item["epic_id"] and item["filing"] == "epic":
        await recompute_epic(repo, item["epic_id"], actor=actor, via="api", now=now)
    return await repo.first("select * from items where id = ?", (item_id,))


TABLES = {"epic": "epics", "item": "items", "task": "tasks"}


async def _endpoint(repo, typ, id_):
    return await _one(repo, f"select * from {TABLES[typ]} where id = ?", (id_,), f"{typ} {id_} not found")


def _touch(typ, row, now):
    out = []
    if typ == "task":
        out.append(("update tasks set last_activity_at = ?, updated_at = ? where id = ?", (now, now, row["id"])))
    eid = row["id"] if typ == "epic" else row["epic_id"]
    if eid:
        out.append(("update epics set last_activity_at = ?, updated_at = ? where id = ?", (now, now, eid)))
    return out


async def create_relation(repo, *, body: RelationIn, actor, now):
    if (body.from_type, body.from_id) == (body.to_type, body.to_id):
        raise ValidationError("a relation cannot point at itself")
    a = await _endpoint(repo, body.from_type, body.from_id)
    b = await _endpoint(repo, body.to_type, body.to_id)
    args = (body.from_type, body.from_id, body.to_type, body.to_id)
    if await repo.first("select id from relations where kind='blocks' and from_type=? and from_id=? "
                        "and to_type=? and to_id=?", args):
        raise Conflict("relation exists")
    payload = {"kind": "blocks", **body.model_dump()}
    await _batch(repo, [
        ("insert into relations(kind, from_type, from_id, to_type, to_id, created_at) "
         "values ('blocks', ?, ?, ?, ?, ?)", (*args, now)),
        (EVENT_BY_SQL.format(table="relations", where="kind='blocks' and from_type=? and from_id=? "
                             "and to_type=? and to_id=?"),
         (now, actor, "relation", "relation.created", json.dumps(payload), *args)),
        *_touch(body.from_type, a, now), *_touch(body.to_type, b, now),
    ], "relation exists")
    return await repo.first("select * from relations where kind='blocks' and from_type=? and from_id=? "
                            "and to_type=? and to_id=?", args)


async def delete_relation(repo, *, relation_id, actor, now):
    r = await _one(repo, "select * from relations where id = ?", (relation_id,), f"relation {relation_id} not found")
    payload = {k: r[k] for k in ("kind", "from_type", "from_id", "to_type", "to_id")}
    stmts = [
        ("delete from relations where id = ?", (relation_id,)),
        _ev(now, actor, "relation", relation_id, "relation.deleted", payload),
    ]
    for typ, id_ in ((r["from_type"], r["from_id"]), (r["to_type"], r["to_id"])):
        row = await repo.first(f"select * from {TABLES[typ]} where id = ?", (id_,))
        if row:
            stmts += _touch(typ, row, now)
    await repo.batch(stmts)


async def put_source(repo, *, name, stall_hours, actor, now):
    await repo.batch([
        ("insert into sources(name, stall_hours, updated_at) values (?, ?, ?) "
         "on conflict(name) do update set stall_hours = excluded.stall_hours, updated_at = excluded.updated_at",
         (name, stall_hours, now)),
        _ev(now, actor, "source", 0, "source.updated", {"name": name, "stall_hours": stall_hours}),
    ])
    return await repo.first("select * from sources where name = ?", (name,))


# --- tasks ---

TASK_FIELDS = ("summary", "description", "done_when", "owner", "waiting_on", "type", "priority", "refs")
TASK_NOT_NULL = ("summary", "description", "done_when", "owner", "type", "priority", "refs")
TASK_BY_KEY = "(select id from tasks where key = ?)"
AUTO_DONE_WHEN = "The linked work is live."
OPEN_STATUSES = ("todo", "in_progress", "review")


async def _item(repo, item_id):
    return await _one(repo, "select * from items where id = ?", (item_id,), f"item {item_id} not found")


async def _task(repo, key):
    return await _one(repo, "select * from tasks where key = ?", (key,), f"task {key} not found")


async def _next_seq(repo, project_id) -> int:
    row = await repo.first("select max(seq) as m from tasks where project_id = ?", (project_id,))
    return (row["m"] or 0) + 1


async def _project_key(repo, project_id) -> str:
    return (await repo.first("select key from projects where id = ?", (project_id,)))["key"]


def _touch_epic(eid, now):
    return [("update epics set last_activity_at = ?, updated_at = ? where id = ?", (now, now, eid))] if eid else []


def _touch_task(tid, now):
    return [("update tasks set last_activity_at = ?, updated_at = ? where id = ?", (now, now, tid))]


def item_origin(item: dict) -> str:
    return item.get("url") or f"{item['source']}:{item['external_id']}"


def auto_task_stmts(item: dict, *, project_id, epic_id, seq, key, actor, now, via="api") -> list:
    """Insert a task made from an item (epic tag, filing) and its task.created event. The item is
    found by (source, external_id), so it may be inserted later in the same batch."""
    owner = ((item.get("owner") or "").strip() or item["source"])[:100]
    summary = item["title"].strip()[:300] or key
    payload = {"key": key, "project_id": project_id, "epic_id": epic_id, "summary": summary,
               "origin": item_origin(item)}
    return [
        ("insert into tasks(project_id, epic_id, seq, key, type, summary, description, done_when, status, "
         "priority, owner, waiting_on, reporter, refs, origin_item_id, last_activity_at, created_at, updated_at) "
         "values (?, ?, ?, ?, 'task', ?, ?, ?, 'todo', 'medium', ?, ?, ?, '[]', "
         "(select id from items where source = ? and external_id = ?), ?, ?, ?)",
         (project_id, epic_id, seq, key, summary, f"Created from {item_origin(item)}", AUTO_DONE_WHEN, owner,
          item.get("waiting_on"), actor, item["source"], item["external_id"], now, now, now)),
        ("insert into events(at, actor, via, subject_type, subject_id, kind, payload) "
         "select ?, ?, ?, 'task', id, 'task.created', ? from tasks where key = ?",
         (now, actor, via, json.dumps(payload), key)),
    ]


def _link_stmts(item, *, task_sql, task_args, epic_id, project_id, actor, now, payload) -> list:
    """Point an item at a task (task_sql selects its id), following the task's epic and project."""
    filing = "epic" if epic_id else "standalone"
    return [
        (f"update items set task_id = {task_sql}, epic_id = ?, project_id = ?, filing = ?, updated_at = ? "
         "where id = ?", (*task_args, epic_id, project_id, filing, now, item["id"])),
        _ev(now, actor, "item", item["id"], "item.linked", payload),
        (f"update tasks set last_activity_at = ?, updated_at = ? where id = {task_sql}", (now, now, *task_args)),
        *_touch_epic(epic_id, now), *_touch_epic(item["epic_id"] if item["epic_id"] != epic_id else None, now),
    ]


async def _resolve_epic(repo, epic_key, project_id):
    if epic_key is None:
        return None
    epic = await _epic(repo, epic_key)
    if epic["project_id"] != project_id:
        raise ValidationError(f"epic {epic_key} is not in this task's project")
    return epic


async def create_task(repo, *, project_key, body: TaskIn, actor, now) -> dict:
    project = await _project(repo, project_key)
    epic = await _resolve_epic(repo, body.epic_key, project["id"])
    epic_id = epic["id"] if epic else None
    item = await _item(repo, body.item_id) if body.item_id is not None else None
    seq = await _next_seq(repo, project["id"])
    key = f"{project_key}-{seq}"
    fields = {k: getattr(body, k) for k in TASK_FIELDS}
    fields["refs"] = json.dumps(body.refs)
    cols = ["project_id", "epic_id", "seq", "key", *fields, "status", "reporter", "last_activity_at",
            "created_at", "updated_at"]
    vals = [project["id"], epic_id, seq, key, *fields.values(), "todo", actor, now, now, now]
    payload = {"key": key, "epic_key": body.epic_key, **body.model_dump(exclude={"epic_key"})}
    stmts = [
        (f"insert into tasks({', '.join(cols)}) values ({', '.join('?' * len(cols))})", vals),
        (EVENT_BY_SQL.format(table="tasks", where="key = ?"),
         (now, actor, "task", "task.created", json.dumps(payload), key)),
        *_touch_epic(epic_id, now),
    ]
    if item is not None:
        stmts += _link_stmts(item, task_sql=TASK_BY_KEY, task_args=(key,), epic_id=epic_id,
                             project_id=project["id"], actor=actor, now=now, payload={"task_key": key})
    await _batch(repo, stmts, f"task {key} exists")
    await recompute_epics(repo, {epic_id, item and item["epic_id"]} - {None}, actor=actor, via="api", now=now)
    return await _task(repo, key)


async def _move_task(repo, task, epic_id, *, actor, now, extra=None):
    """Re-point a task (and its linked items) at another epic of its project, or No epic."""
    epic_key = (await repo.first("select key from epics where id = ?", (epic_id,)))["key"] if epic_id else None
    changed = {**(extra or {}), "epic_key": epic_key}
    stmts = [
        ("update tasks set epic_id = ?, last_activity_at = ?, updated_at = ? where id = ?",
         (epic_id, now, now, task["id"])),
        ("update items set epic_id = ?, filing = ?, updated_at = ? where task_id = ?",
         (epic_id, "epic" if epic_id else "standalone", now, task["id"])),
        _ev(now, actor, "task", task["id"], "task.updated", changed),
        *_touch_epic(task["epic_id"], now), *_touch_epic(epic_id, now),
    ]
    await repo.batch(stmts)
    await recompute_epics(repo, {task["epic_id"], epic_id} - {None}, actor=actor, via="api", now=now)


async def patch_task(repo, *, key, changes: TaskPatch, actor, now) -> dict:
    given = {k: getattr(changes, k) for k in changes.model_fields_set}
    if not given:
        raise ValidationError("empty patch")
    for k in TASK_NOT_NULL:
        if k in given and given[k] is None:
            raise ValidationError(f"{k} cannot be null")
    task = await _task(repo, key)
    if "waiting_on" in given and given["waiting_on"] is None and task["status"] not in ("done", "canceled"):
        raise ValidationError("waiting_on is required while the task is open")
    move = "epic_key" in given
    new_epic = await _resolve_epic(repo, given.pop("epic_key", None), task["project_id"]) if move else None
    if "refs" in given:
        given["refs"] = json.dumps(given["refs"])
    changed = {k: v for k, v in given.items() if task[k] != v}
    new_epic_id = new_epic["id"] if new_epic else None
    if changed:
        sets = ", ".join(f"{k} = ?" for k in changed)
        await repo.batch([
            (f"update tasks set {sets}, last_activity_at = ?, updated_at = ? where id = ?",
             [*changed.values(), now, now, task["id"]]),
            *([] if move and new_epic_id != task["epic_id"] else
              [_ev(now, actor, "task", task["id"], "task.updated", _payload(changed))]),
            *_touch_epic(task["epic_id"], now),
        ])
    if move and new_epic_id != task["epic_id"]:
        await _move_task(repo, task, new_epic_id, actor=actor, now=now, extra=_payload(changed))
    elif changed:
        await recompute_epics(repo, {task["epic_id"]} - {None}, actor=actor, via="api", now=now)
    return await _task(repo, key)


def _payload(changed):
    return {k: json.loads(v) if k == "refs" else v for k, v in changed.items()}


async def _live_link_count(repo, task_id) -> int:
    row = await repo.first("select count(*) as n from items where task_id = ? and filing != 'ignored' "
                           "and status_category != 'canceled'", (task_id,))
    return row["n"]


async def set_task_status(repo, *, key, status, actor, human: bool, now) -> dict:
    task = await _task(repo, key)
    if task["merged_into"] is not None:
        raise ValidationError("a merged task stays canceled")
    if status != "canceled" and await _live_link_count(repo, task["id"]):
        raise ValidationError("status follows its links")
    if status in OPEN_STATUSES and not task["waiting_on"]:
        raise ValidationError("waiting_on is required while the task is open")
    confirmed = now if status == "done" and human else None
    await repo.batch([
        ("update tasks set status = ?, done_confirmed_at = ?, last_activity_at = ?, updated_at = ? where id = ?",
         (status, confirmed, now, now, task["id"])),
        _ev(now, actor, "task", task["id"], "task.status_changed",
            {"from": task["status"], "to": status, "confirmed": bool(confirmed)}),
        *_touch_epic(task["epic_id"], now),
    ])
    await recompute_epics(repo, {task["epic_id"]} - {None}, actor=actor, via="api", now=now)
    return await _task(repo, key)


async def confirm_task_done(repo, *, key, actor, human: bool, now) -> dict:
    if not human:
        raise Forbidden("only a human can confirm a task done")
    task = await _task(repo, key)
    if task["status"] != "done" or task["done_confirmed_at"] or await _live_link_count(repo, task["id"]):
        raise ValidationError("task is not waiting for a human to confirm it")
    await repo.batch([
        ("update tasks set done_confirmed_at = ?, last_activity_at = ?, updated_at = ? where id = ?",
         (now, now, now, task["id"])),
        _ev(now, actor, "task", task["id"], "task.done_confirmed", {"done_confirmed_at": now}),
        *_touch_epic(task["epic_id"], now),
    ])
    await recompute_epics(repo, {task["epic_id"]} - {None}, actor=actor, via="api", now=now)
    return await _task(repo, key)


async def merge_tasks(repo, *, key, into, actor, now) -> dict:
    a, b = await _task(repo, key), await _task(repo, into)
    if a["id"] == b["id"]:
        raise ValidationError("a task cannot be merged into itself")
    if a["project_id"] != b["project_id"]:
        raise ValidationError("tasks can only be merged within one project")
    if "canceled" in (a["status"], b["status"]):
        raise ValidationError("cannot merge from or into a canceled task")
    refs = json.loads(b["refs"] or "[]")
    for r in [a["key"], *json.loads(a["refs"] or "[]")]:
        if r not in refs and r != b["key"]:
            refs.append(r)
    filing = "epic" if b["epic_id"] else "standalone"
    await repo.batch([
        ("insert into events(at, actor, via, subject_type, subject_id, kind, payload) "
         "select ?, ?, 'api', 'item', id, 'item.linked', ? from items where task_id = ?",
         (now, actor, json.dumps({"task_key": b["key"], "from_task_key": a["key"], "merge": True}), a["id"])),
        ("update items set task_id = ?, epic_id = ?, project_id = ?, filing = ?, updated_at = ? where task_id = ?",
         (b["id"], b["epic_id"], b["project_id"], filing, now, a["id"])),
        ("update tasks set refs = ?, last_activity_at = ?, updated_at = ? where id = ?",
         (json.dumps(refs), now, now, b["id"])),
        ("update tasks set status = 'canceled', merged_into = ?, last_activity_at = ?, updated_at = ? where id = ?",
         (b["id"], now, now, a["id"])),
        _ev(now, actor, "task", a["id"], "task.merged", {"into": b["key"]}),
        _ev(now, actor, "task", b["id"], "task.updated", {"refs": refs, "merged_from": a["key"]}),
        *_touch_epic(a["epic_id"], now), *_touch_epic(b["epic_id"] if b["epic_id"] != a["epic_id"] else None, now),
    ])
    await recompute_epics(repo, {a["epic_id"], b["epic_id"]} - {None}, actor=actor, via="api", now=now)
    return await _task(repo, into)


async def link_item(repo, *, item_id, task_key, actor, now) -> dict:
    item = await _item(repo, item_id)
    task = await _task(repo, task_key)
    if task["status"] == "canceled":
        raise ValidationError(f"task {task_key} is canceled")
    if item["task_id"] == task["id"]:
        return item
    await repo.batch(_link_stmts(item, task_sql="?", task_args=(task["id"],), epic_id=task["epic_id"],
                                 project_id=task["project_id"], actor=actor, now=now,
                                 payload={"task_key": task_key}))
    await recompute_epics(repo, {item["epic_id"], task["epic_id"]} - {None}, actor=actor, via="api", now=now)
    return await _item(repo, item_id)


async def unlink_item(repo, *, item_id, actor, now, filing="unfiled") -> dict:
    item = await _item(repo, item_id)
    if item["filing"] == filing and item["task_id"] is None:
        return item
    old = await repo.first("select key from tasks where id = ?", (item["task_id"],)) if item["task_id"] else None
    stmts = [
        ("update items set task_id = null, epic_id = null, filing = ?, updated_at = ? where id = ?",
         (filing, now, item_id)),
        _ev(now, actor, "item", item_id, "item.unlinked" if filing == "unfiled" else "item.filed",
            {"task_key": old and old["key"], "filing": filing}),
        *_touch_epic(item["epic_id"], now),
    ]
    if item["task_id"]:
        stmts += _touch_task(item["task_id"], now)
    await repo.batch(stmts)
    await recompute_epics(repo, {item["epic_id"]} - {None}, actor=actor, via="api", now=now)
    return await _item(repo, item_id)
