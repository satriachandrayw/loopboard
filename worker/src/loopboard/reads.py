"""Read API logic: board, needs-you, stalled, unfiled, epic and task detail, tasks board, projects."""
import json

from .derive import derive_epic, derive_task, effective_category, live_links, open_items
from .model import DONE_HIDE_SECONDS, REVIEW_WARN_AT
from .recompute import _qs, chunks
from .stall import epic_stalled, item_stalled, task_stalled

COLUMNS = (("backlog", "Backlog"), ("todo", "Todo"), ("in_progress", "In progress"),
           ("review", "Review"), ("done", "Done"))
GROUPS = ("agent", "human", "source")
TASK_COLUMNS = ("todo", "in_progress", "review", "done")
OPEN_TASK = ("todo", "in_progress", "review")
# Links summary: the most advanced state among a source's live links wins.
LINK_STATES = ("todo", "blocked", "open", "running", "review", "merged", "done", "live")

TASKS_SQL = ("select t.*, p.key as project_key, e.key as epic_key, m.key as merged_into_key "
             "from tasks t join projects p on p.id = t.project_id left join epics e on e.id = t.epic_id "
             "left join tasks m on m.id = t.merged_into")
LINKS_SQL = "select i.* from items i join tasks t on t.id = i.task_id"


def group_of(waiting_on) -> str:
    prefix = (waiting_on or "").split(":", 1)[0]
    return prefix if prefix in GROUPS else "source"


def item_ref(i: dict) -> str:
    return f"{i['source']}:{i['external_id']}"


async def thresholds(repo) -> dict:
    rows = await repo.query("select name, stall_hours from sources")
    return {r["name"]: r["stall_hours"] for r in rows}


async def load_tasks(repo, *, project_id=None, epic_ids=None, keys=None) -> list[dict]:
    """Tasks with their linked items and derived state: one tasks select and one items select
    (per 99 epic ids or keys), never one query per task."""
    if epic_ids is not None or keys is not None:
        col, vals = ("t.epic_id", sorted(set(epic_ids))) if epic_ids is not None else ("t.key", sorted(set(keys)))
        parts = [(f" where {col} in ({_qs(len(p))})", p) for p in chunks(vals)]
    elif project_id is not None:
        parts = [(" where t.project_id = ?", [project_id])]
    else:
        parts = [("", [])]
    tasks, items = [], []
    for where, args in parts:
        tasks += await repo.query(TASKS_SQL + where + " order by t.project_id, t.seq", args)
        items += await repo.query(LINKS_SQL + where + " order by i.id", args)
    by_task: dict[int, list[dict]] = {}
    for i in items:
        by_task.setdefault(i["task_id"], []).append(i)
    return [{"task": t, "items": by_task.get(t["id"], []),
             "derived": derive_task(t, by_task.get(t["id"], []), t.get("merged_into_key"))} for t in tasks]


async def load_epics(repo, *, project_key=None) -> list[dict]:
    """Epics (with project_key), each with its tasks (load_tasks rows), their derived states and
    the items linked to its non-canceled tasks."""
    sql = "select e.*, p.key as project_key from epics e join projects p on p.id = e.project_id"
    args: tuple = ()
    if project_key:
        sql += " where p.key = ?"
        args = (project_key,)
    epics = await repo.query(sql + " order by e.id", args)
    if project_key and epics:
        tasks = await load_tasks(repo, project_id=epics[0]["project_id"])
    elif project_key:
        tasks = []
    else:
        tasks = await load_tasks(repo)
    by_epic: dict[int, list[dict]] = {}
    for t in tasks:
        if t["task"]["epic_id"] is not None:
            by_epic.setdefault(t["task"]["epic_id"], []).append(t)
    return [_epic_row(e, by_epic.get(e["id"], [])) for e in epics]


def _epic_row(e, tasks) -> dict:
    items = [i for t in tasks if t["derived"].status != "canceled" for i in t["items"]]
    return {"epic": e, "tasks": tasks, "items": items}


def _derive(row, now):
    return derive_epic(row["epic"], [t["derived"] for t in row["tasks"]], now)


def _waiting_since(epic, items) -> int:
    return max([epic["last_activity_at"]] + [i["last_activity_at"] for i in open_items(items)])


def _card(e, items, d, now, th) -> dict:
    return {
        "id": e["id"], "key": e["key"], "title": e["title"], "goal": e["goal"],
        "project_key": e["project_key"],
        "column": d.board_column, "stage": e["stage"],
        "progress": {"done": d.done, "total": d.total},
        "owner": e["owner"], "waiting_on": e["waiting_on"],
        "waiting_since": _waiting_since(e, items),
        "stalled": epic_stalled(e, items, d, now, th),
        "flags": d.flags, "review_owner": d.review_owner,
    }


def link_state(i: dict) -> str:
    if i.get("merged_at"):
        return "live" if i.get("live_at") else "merged"
    c = effective_category(i)
    if i["source"] == "github" and c != "done":
        return "open"
    return {"backlog": "todo", "in_progress": "running"}.get(c, c)


def links_summary(items) -> dict:
    out: dict[str, dict] = {}
    for i in live_links(items):
        s = out.setdefault(i["source"], {"count": 0, "state": "todo"})
        s["count"] += 1
        st = link_state(i)
        if LINK_STATES.index(st) > LINK_STATES.index(s["state"]):
            s["state"] = st
    return out


def task_activity(task, items) -> int:
    """When the task last moved: itself or any live link."""
    return max([task["last_activity_at"]] + [i["last_activity_at"] for i in live_links(items)])


def task_view(task, items, derived, *, project_key, epic_key, now, th) -> dict:
    open_links = [i for i in live_links(items) if effective_category(i) not in ("done", "canceled")]
    return {
        "id": task["id"], "key": task["key"], "type": task["type"], "summary": task["summary"],
        "description": task["description"], "done_when": task["done_when"],
        "project_key": project_key, "epic_key": epic_key,
        "status": derived.status, "flags": derived.flags, "reason": derived.reason,
        "priority": task["priority"], "owner": task["owner"], "waiting_on": task["waiting_on"],
        "waiting_since": max([task["last_activity_at"]] + [i["last_activity_at"] for i in open_links]),
        "stalled": task_stalled(task, items, derived, now, th),
        "refs": json.loads(task["refs"] or "[]"), "reporter": task["reporter"],
        "links_summary": links_summary(items),
        "last_activity_at": task_activity(task, items),
    }


def _view(row, now, th) -> dict:
    t = row["task"]
    return task_view(t, row["items"], row["derived"], project_key=t["project_key"], epic_key=t["epic_key"],
                     now=now, th=th)


async def board(repo, *, now, project_key=None, waiting_on=None) -> dict:
    th = await thresholds(repo)
    cols = {c: [] for c, _ in COLUMNS}
    for row in await load_epics(repo, project_key=project_key):
        e, items = row["epic"], row["items"]
        d = _derive(row, now)
        if d.hidden or d.board_column not in cols:
            continue
        if waiting_on and group_of(e["waiting_on"]) != waiting_on:
            continue
        cols[d.board_column].append(_card(e, items, d, now, th))
    out = []
    for c, label in COLUMNS:
        cards = sorted(cols[c], key=lambda x: x["id"])
        warn = c == "review" and len(cards) > REVIEW_WARN_AT
        out.append({"column": c, "label": label, "count": len(cards), "warn": warn, "cards": cards})
    return {"columns": out}


def _human(w) -> bool:
    return bool(w) and w.startswith("human:")


async def _project_id(repo, project_key):
    """None when no filter; -1 for an unknown key so the filter matches nothing."""
    if not project_key:
        return None
    p = await repo.first("select id from projects where key = ?", (project_key,))
    return p["id"] if p else -1


async def _shown_tasks(repo, project_key, now):
    """Open-epic tasks and No-epic tasks of the project filter, with their epic's derived state."""
    rows = await load_epics(repo, project_key=project_key)
    hidden = {r["epic"]["id"] for r in rows if _derive(r, now).hidden}
    pid = await _project_id(repo, project_key)
    tasks = await load_tasks(repo, project_id=pid) if pid is not None else await load_tasks(repo)
    return [t for t in tasks if t["task"]["epic_id"] not in hidden]


async def needs_you(repo, *, now, project_key=None) -> list[dict]:
    rows = []
    for row in await load_epics(repo, project_key=project_key):
        e, items = row["epic"], row["items"]
        d = _derive(row, now)
        if d.hidden or d.board_column in ("done", "canceled"):
            continue
        reasons = []
        if _human(e["waiting_on"]):
            reasons.append("waiting on you")
        if "awaiting_approval" in d.flags:
            reasons.append("awaiting your approval")
        if "awaiting_confirmation" in d.flags:
            reasons.append("awaiting your confirmation")
        if "merged_not_live" in d.flags:
            reasons.append("merged, not live")
        if "blocked_needs_input" in d.flags:
            reasons.append("blocked: needs your input")
        if d.review_owner == "human":
            reasons.append("review · you")
        if reasons:
            rows.append({"kind": "epic", "id": e["id"], "ref": e["key"], "title": e["title"],
                         "waiting_on": e["waiting_on"], "waiting_since": _waiting_since(e, items),
                         "reasons": reasons})
    th = await thresholds(repo)
    for row in await _shown_tasks(repo, project_key, now):
        t, d = row["task"], row["derived"]
        if d.status not in OPEN_TASK:
            continue
        reasons = []
        if _human(t["waiting_on"]):
            reasons.append("waiting on you")
        if "awaiting_confirmation" in d.flags:
            reasons.append("awaiting your confirmation")
        if t["epic_id"] is None:  # an epic's row already carries these for its tasks
            if "merged_not_live" in d.flags:
                reasons.append("merged, not live")
            if "blocked_needs_input" in d.flags:
                reasons.append("blocked: needs your input")
        if reasons:
            v = _view(row, now, th)
            rows.append({"kind": "task", "id": t["id"], "ref": t["key"], "title": t["summary"],
                         "epic_key": t["epic_key"], "waiting_on": t["waiting_on"],
                         "waiting_since": v["waiting_since"], "reasons": reasons})
    return sorted(rows, key=lambda r: (r["waiting_since"], r["kind"], r["id"]))


async def stalled(repo, *, now, waiting_on=None, project_key=None) -> list[dict]:
    th = await thresholds(repo)
    rows = []

    def add(kind, id_, ref, title, w_on, since, extra):
        g = group_of(w_on)
        if waiting_on and g != waiting_on:
            return
        rows.append({"kind": kind, "id": id_, "ref": ref, "title": title, "waiting_on": w_on,
                     "waiting_group": g, "waiting_since": since,
                     "stalled_for_hours": round((now - since) / 3600, 1), **extra})

    canceled = set()
    for row in await load_epics(repo, project_key=project_key):
        e, items = row["epic"], row["items"]
        if e["manual_column"] == "canceled":
            canceled.add(e["id"])
        d = _derive(row, now)
        if epic_stalled(e, items, d, now, th):
            add("epic", e["id"], e["key"], e["title"], e["waiting_on"], _waiting_since(e, items), {})
    pid = await _project_id(repo, project_key)
    for row in await load_tasks(repo, project_id=pid) if pid is not None else await load_tasks(repo):
        t = row["task"]
        if t["epic_id"] in canceled or not task_stalled(t, row["items"], row["derived"], now, th):
            continue
        add("task", t["id"], t["key"], t["summary"], t["waiting_on"], task_activity(t, row["items"]),
            {"epic_key": t["epic_key"]})
    return sorted(rows, key=lambda r: (r["waiting_since"], r["kind"], r["id"]))


async def unfiled(repo, *, now, project_key=None) -> list[dict]:
    sql = ("select i.id, i.source, i.external_id, i.title, i.url, i.owner, i.waiting_on, "
           "i.last_activity_at, p.key as project_key, i.status_category, i.merged_at, i.live_at "
           "from items i left join projects p on p.id = i.project_id "
           "where i.filing = 'unfiled' and i.status_category != 'canceled'")
    args: tuple = ()
    if project_key:
        sql += " and p.key = ?"
        args = (project_key,)
    rows = await repo.query(sql + " order by i.last_activity_at, i.id", args)
    # `category` folds a merged-and-live review item into done, as everywhere else.
    return [{**r, "category": effective_category(r)} for r in rows]


async def projects(repo) -> list[dict]:
    return await repo.query("select id, key, name, created_at from projects order by key")


def _link_entry(i, now, th) -> dict:
    cat = effective_category(i)
    if cat == "backlog":
        cat = "todo"
    return {
        "id": i["id"], "ref": item_ref(i), "source": i["source"], "external_id": i["external_id"],
        "title": i["title"], "url": i["url"], "status_category": i["status_category"],
        "category": cat, "owner": i["owner"], "waiting_on": i["waiting_on"],
        "next_step": i["next_step"], "last_activity_at": i["last_activity_at"],
        "merged_at": i["merged_at"], "live_at": i["live_at"], "filing": i["filing"],
        "stalled": item_stalled(i, now, th)}


def _events(rows):
    for ev in rows:
        ev["payload"] = json.loads(ev["payload"])
    return rows


async def epic_detail(repo, *, key, now):
    e = await repo.first(
        "select e.*, p.key as project_key from epics e join projects p on p.id = e.project_id "
        "where e.key = ?", (key,))
    if e is None:
        return None
    th = await thresholds(repo)
    row = _epic_row(e, await load_tasks(repo, epic_ids=[e["id"]]))
    d = _derive(row, now)
    card = _card(e, row["items"], d, now, th)
    card.update({k: e[k] for k in ("next_step", "home_url", "spec_url", "plan_url")})
    tasks = [_view(t, now, th) for t in row["tasks"] if t["derived"].status != "canceled"]
    tsub = "select id from tasks where epic_id = ?"
    isub = f"select id from items where task_id in ({tsub})"
    relations = await repo.query(
        "select * from relations where (from_type='epic' and from_id=?) or (to_type='epic' and to_id=?) "
        f"or (from_type='task' and from_id in ({tsub})) or (to_type='task' and to_id in ({tsub})) "
        f"or (from_type='item' and from_id in ({isub})) or (to_type='item' and to_id in ({isub})) order by id",
        (e["id"],) * 6)
    events = await repo.query(
        "select * from events where (subject_type='epic' and subject_id=?) "
        f"or (subject_type='task' and subject_id in ({tsub})) "
        f"or (subject_type='item' and subject_id in ({isub})) order by at desc, id desc limit 50",
        (e["id"],) * 3)
    return {"epic": card, "tasks": tasks, "relations": relations, "events": _events(events)}


async def task_detail(repo, *, key, now):
    rows = await load_tasks(repo, keys=[key])
    if not rows:
        return None
    row = rows[0]
    th = await thresholds(repo)
    t = row["task"]
    out = _view(row, now, th)
    out["merged_into"] = t["merged_into_key"]
    out["created_at"], out["updated_at"] = t["created_at"], t["updated_at"]
    out["done_confirmed_at"] = t["done_confirmed_at"]
    out["links"] = [_link_entry(i, now, th) for i in row["items"]]
    events = await repo.query(
        "select * from events where (subject_type='task' and subject_id=?) "
        "or (subject_type='item' and subject_id in (select id from items where task_id = ?)) "
        "order by at desc, id desc limit 50", (t["id"], t["id"]))
    out["events"] = _events(events)
    return out


async def task_card(repo, *, key, now):
    """The task as the boards show it (task_view), or None."""
    rows = await load_tasks(repo, keys=[key])
    return _view(rows[0], now, await thresholds(repo)) if rows else None


async def tasks_board(repo, *, project_key, now):
    """One project's tasks in swimlanes: its shown epics in board order, then No epic."""
    p = await repo.first("select id from projects where key = ?", (project_key,))
    if p is None:
        return None
    th = await thresholds(repo)
    order = [c for c, _ in COLUMNS]
    epic_rows = []
    for row in await load_epics(repo, project_key=project_key):
        d = _derive(row, now)
        if d.hidden or d.board_column not in order:
            continue
        epic_rows.append((order.index(d.board_column), row["epic"]["id"], row, d))
    epic_rows.sort(key=lambda x: (x[0], x[1]))
    lanes: list[dict] = []
    lane_of: dict[int | None, dict] = {}
    for _, eid, row, d in epic_rows:
        e = row["epic"]
        lane_of[eid] = {"epic": {"key": e["key"], "title": e["title"],
                                 "progress": {"done": d.done, "total": d.total}},
                        "tasks": {c: [] for c in TASK_COLUMNS}}
        lanes.append(lane_of[eid])
    lane_of[None] = {"epic": None, "tasks": {c: [] for c in TASK_COLUMNS}}
    lanes.append(lane_of[None])
    for row in await load_tasks(repo, project_id=p["id"]):
        t, d = row["task"], row["derived"]
        lane = lane_of.get(t["epic_id"])
        if lane is None or d.status not in TASK_COLUMNS:
            continue
        if d.status == "done" and now - task_activity(t, row["items"]) > DONE_HIDE_SECONDS:
            continue
        lane["tasks"][d.status].append(_view(row, now, th))
    return {"project": project_key, "columns": list(TASK_COLUMNS), "lanes": lanes}
