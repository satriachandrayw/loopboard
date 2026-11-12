"""Read API logic: board, needs-you, stalled, unfiled, epic detail, projects."""
import json

from .derive import derive_epic, effective_category, open_items
from .model import OPEN_CATEGORIES, REVIEW_WARN_AT
from .stall import ITEMS_FOR_STALL, epic_stalled, item_stalled, stall_eligible

COLUMNS = (("backlog", "Backlog"), ("todo", "Todo"), ("in_progress", "In progress"),
           ("review", "Review"), ("done", "Done"))
GROUPS = ("agent", "human", "source")
TASK_GROUPS = ("todo", "in_progress", "blocked", "review", "done")


def group_of(waiting_on) -> str:
    prefix = (waiting_on or "").split(":", 1)[0]
    return prefix if prefix in GROUPS else "source"


def item_ref(i: dict) -> str:
    return f"{i['source']}:{i['external_id']}"


async def thresholds(repo) -> dict:
    rows = await repo.query("select name, stall_hours from sources")
    return {r["name"]: r["stall_hours"] for r in rows}


async def load_epics(repo, *, project_key=None) -> list[dict]:
    """Epics (with project_key) each carrying its filing='epic' items and derived state."""
    sql = ("select e.*, p.key as project_key from epics e join projects p on p.id = e.project_id")
    args: tuple = ()
    if project_key:
        sql += " where p.key = ?"
        args = (project_key,)
    epics = await repo.query(sql + " order by e.id", args)
    items = await repo.query("select * from items where filing = 'epic' and epic_id is not null")
    by_epic: dict[int, list[dict]] = {}
    for i in items:
        by_epic.setdefault(i["epic_id"], []).append(i)
    return [{"epic": e, "items": by_epic.get(e["id"], [])} for e in epics]


def _waiting_since(epic, items) -> int:
    return max([epic["last_activity_at"]] + [i["last_activity_at"] for i in open_items(items)])


def _card(e, items, d, now, th) -> dict:
    return {
        "id": e["id"], "key": e["key"], "title": e["title"], "project_key": e["project_key"],
        "column": d.board_column, "stage": e["stage"],
        "progress": {"done": d.done, "total": d.total},
        "owner": e["owner"], "waiting_on": e["waiting_on"],
        "waiting_since": _waiting_since(e, items),
        "stalled": epic_stalled(e, items, d, now, th),
        "flags": d.flags, "review_owner": d.review_owner,
    }


async def board(repo, *, now, project_key=None, waiting_on=None) -> dict:
    th = await thresholds(repo)
    cols = {c: [] for c, _ in COLUMNS}
    for row in await load_epics(repo, project_key=project_key):
        e, items = row["epic"], row["items"]
        d = derive_epic(e, items, now)
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


async def needs_you(repo, *, now, project_key=None) -> list[dict]:
    pid = await _project_id(repo, project_key)
    rows = []
    for row in await load_epics(repo, project_key=project_key):
        e, items = row["epic"], row["items"]
        d = derive_epic(e, items, now)
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
    for i in await repo.query("select * from items where filing = 'standalone'"):
        if pid is not None and i["project_id"] != pid:
            continue
        if effective_category(i) in OPEN_CATEGORIES and _human(i["waiting_on"]):
            rows.append({"kind": "item", "id": i["id"], "ref": item_ref(i), "title": i["title"],
                         "url": i["url"], "waiting_on": i["waiting_on"],
                         "waiting_since": i["last_activity_at"], "reasons": ["waiting on you"]})
    return sorted(rows, key=lambda r: (r["waiting_since"], r["kind"], r["id"]))


async def stalled(repo, *, now, waiting_on=None, project_key=None) -> list[dict]:
    pid = await _project_id(repo, project_key)
    th = await thresholds(repo)
    rows = []

    def add(kind, id_, ref, title, w_on, since, extra):
        g = group_of(w_on)
        if waiting_on and g != waiting_on:
            return
        rows.append({"kind": kind, "id": id_, "ref": ref, "title": title, "waiting_on": w_on,
                     "waiting_group": g, "waiting_since": since,
                     "stalled_for_hours": round((now - since) / 3600, 1), **extra})

    for row in await load_epics(repo, project_key=project_key):
        e, items = row["epic"], row["items"]
        d = derive_epic(e, items, now)
        if epic_stalled(e, items, d, now, th):
            add("epic", e["id"], e["key"], e["title"], e["waiting_on"], _waiting_since(e, items), {})
    for i in await repo.query(ITEMS_FOR_STALL):
        if pid is not None and (i["project_id"] or i["epic_project_id"]) != pid:
            continue
        if stall_eligible(i) and item_stalled(i, now, th):
            add("item", i["id"], item_ref(i), i["title"], i["waiting_on"], i["last_activity_at"],
                {"url": i["url"], "source": i["source"], "external_id": i["external_id"]})
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


async def epic_detail(repo, *, key, now):
    e = await repo.first(
        "select e.*, p.key as project_key from epics e join projects p on p.id = e.project_id "
        "where e.key = ?", (key,))
    if e is None:
        return None
    th = await thresholds(repo)
    items = await repo.query("select * from items where epic_id = ? and filing = 'epic' order by id",
                             (e["id"],))
    d = derive_epic(e, items, now)
    card = _card(e, items, d, now, th)
    card.update({k: e[k] for k in ("goal", "next_step", "home_url", "spec_url", "plan_url")})
    tasks = {g: [] for g in TASK_GROUPS}
    for i in items:
        if i["status_category"] == "canceled":
            continue
        cat = effective_category(i)
        if cat == "backlog":
            cat = "todo"
        tasks[cat].append({
            "id": i["id"], "ref": item_ref(i), "source": i["source"], "external_id": i["external_id"],
            "title": i["title"], "url": i["url"], "status_category": i["status_category"],
            "category": cat, "owner": i["owner"], "waiting_on": i["waiting_on"],
            "next_step": i["next_step"], "last_activity_at": i["last_activity_at"],
            "merged_at": i["merged_at"], "live_at": i["live_at"],
            "stalled": item_stalled(i, now, th)})
    sub = "select id from items where epic_id = ? and filing = 'epic'"
    relations = await repo.query(
        "select * from relations where (from_type='epic' and from_id=?) or (to_type='epic' and to_id=?) "
        f"or (from_type='item' and from_id in ({sub})) or (to_type='item' and to_id in ({sub})) order by id",
        (e["id"],) * 4)
    events = await repo.query(
        "select * from events where (subject_type='epic' and subject_id=?) "
        f"or (subject_type='item' and subject_id in ({sub})) order by at desc, id desc limit 50",
        (e["id"],) * 2)
    for ev in events:
        ev["payload"] = json.loads(ev["payload"])
    return {"epic": card, "tasks": tasks, "relations": relations, "events": events}
