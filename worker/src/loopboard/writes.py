"""Write API logic (D1: state change + event in one batch)."""
import json

from .model import EpicIn, EpicPatch, FilingIn, RelationIn, ValidationError
from .recompute import recompute_epic

EVENT = ("insert into events(at, actor, via, subject_type, subject_id, kind, payload) "
         "values(?, ?, 'api', ?, ?, ?, ?)")
EVENT_BY_SQL = ("insert into events(at, actor, via, subject_type, subject_id, kind, payload) "
                "select ?, ?, 'api', ?, id, ?, ? from {table} where {where}")
EPIC_FIELDS = ("title", "goal", "stage", "owner", "next_step", "waiting_on", "home_url", "spec_url",
               "plan_url", "manual_column")
NOT_NULL = ("title", "stage", "manual_column")


class NotFound(LookupError):
    pass


class Conflict(Exception):
    pass


def _ev(now, actor, stype, sid, kind, payload):
    return (EVENT, (now, actor, stype, sid, kind, json.dumps(payload)))


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
    await repo.batch([
        ("insert into projects(key, name, created_at) values (?, ?, ?)", (key, name, now)),
        (EVENT_BY_SQL.format(table="projects", where="key = ?"),
         (now, actor, "project", "project.created", json.dumps({"key": key, "name": name}), key)),
    ])
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
    await repo.batch([
        (f"insert into epics({', '.join(cols)}) values ({', '.join('?' * len(cols))})", vals),
        (EVENT_BY_SQL.format(table="epics", where="key = ?"),
         (now, actor, "epic", "epic.created", json.dumps(payload), key)),
    ])
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
    item = await _one(repo, "select * from items where id = ?", (item_id,), f"item {item_id} not found")
    new = {"filing": body.filing}
    new_epic = None
    if body.filing == "epic":
        if not body.epic_key:
            raise ValidationError("epic_key is required to file under an epic")
        new_epic = await _epic(repo, body.epic_key)
        new.update(epic_id=new_epic["id"], project_id=new_epic["project_id"])
    else:
        new["epic_id"] = None
        if body.project_key:
            new["project_id"] = (await _project(repo, body.project_key))["id"]
        if body.filing == "standalone" and not (body.project_key or item["project_id"]):
            raise ValidationError("standalone needs a project (project_key or the item's project)")
    changed = {k: v for k, v in new.items() if item[k] != v}
    if changed:
        sets = ", ".join(f"{k} = ?" for k in changed)
        stmts = [
            (f"update items set {sets}, updated_at = ? where id = ?", [*changed.values(), now, item_id]),
            _ev(now, actor, "item", item_id, "item.filed", changed),
        ]
        for eid in {item["epic_id"], new.get("epic_id")} - {None}:
            stmts.append(("update epics set last_activity_at = ?, updated_at = ? where id = ?", (now, now, eid)))
        await repo.batch(stmts)
        for eid in sorted({item["epic_id"], new.get("epic_id")} - {None}):
            await recompute_epic(repo, eid, actor=actor, via="api", now=now)
    return await repo.first("select * from items where id = ?", (item_id,))


async def mark_deployed(repo, *, item_id, live_at: int, actor, now):
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


async def _endpoint(repo, typ, id_):
    table = "epics" if typ == "epic" else "items"
    return await _one(repo, f"select * from {table} where id = ?", (id_,), f"{typ} {id_} not found")


def _touch(typ, row, now):
    eid = row["id"] if typ == "epic" else row["epic_id"]
    if not eid:
        return []
    return [("update epics set last_activity_at = ?, updated_at = ? where id = ?", (now, now, eid))]


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
    await repo.batch([
        ("insert into relations(kind, from_type, from_id, to_type, to_id, created_at) "
         "values ('blocks', ?, ?, ?, ?, ?)", (*args, now)),
        (EVENT_BY_SQL.format(table="relations", where="kind='blocks' and from_type=? and from_id=? "
                             "and to_type=? and to_id=?"),
         (now, actor, "relation", "relation.created", json.dumps(payload), *args)),
        *_touch(body.from_type, a, now), *_touch(body.to_type, b, now),
    ])
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
        table = "epics" if typ == "epic" else "items"
        row = await repo.first(f"select * from {table} where id = ?", (id_,))
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
