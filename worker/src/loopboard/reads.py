"""Read API logic: board, needs-you, stalled, unfiled, epic and task detail, tasks board, projects."""
import json

from .derive import derive_epic, derive_task, effective_category, live_links, open_items
from .model import DONE_HIDE_SECONDS, REVIEW_WARN_AT
from .recompute import _qs, chunks
from .stall import OPEN_TASK_STATUSES, epic_stalled, item_stalled, task_stalled

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


def _waiting_since(epic, items, tasks) -> int:
    """The newest open item; with none, the newest of the epic and its open tasks (load_tasks rows),
    the same clock epic_stalled uses."""
    op = open_items(items)
    if op:
        return max([epic["last_activity_at"]] + [i["last_activity_at"] for i in op])
    return max([epic["last_activity_at"]] + [t["task"]["last_activity_at"] for t in tasks
                                             if t["derived"].status in OPEN_TASK_STATUSES])


def _card(e, items, tasks, d, now, th) -> dict:
    return {
        "id": e["id"], "key": e["key"], "title": e["title"], "goal": e["goal"],
        "project_key": e["project_key"],
        "column": d.board_column, "stage": e["stage"],
        "progress": {"done": d.done, "total": d.total},
        "owner": e["owner"], "waiting_on": e["waiting_on"],
        "waiting_since": _waiting_since(e, items, tasks),
        "stalled": epic_stalled(e, items, tasks, d, now, th),
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
        cols[d.board_column].append(_card(e, items, row["tasks"], d, now, th))
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


# --- Needs you: every row carries its question (docs/design-needs-you-questions.md) ---

ASK_ORDER = ("decide", "review", "release", "confirm", "later")
FOLD = "release"  # resolve_ask's answer for merged-not-live work: no row of its own
NO_QUESTION = "No question recorded yet."
ASK_AGENT = "Ask your agent about this task:"
REPLY = "Reply to your agent:"


def _ask(kind, question, answer_how, reply_code, *, auto=True, missing=False, url=None) -> dict:
    return {"ask_kind": kind, "question": question, "answer_how": answer_how, "reply_code": reply_code,
            "auto": auto, "missing_question": missing, "url": url}


def _missing(ref) -> dict:
    return _ask("decide", NO_QUESTION, ASK_AGENT, f"{ref}?", missing=True)


def _pr_name(external_id: str) -> str:
    """`owner/repo#7` -> `repo#7`."""
    repo, _, n = external_id.rpartition("#")
    return f"{repo.rsplit('/', 1)[-1]}#{n}"


def _computed(task, items, flags):
    """Rules 2-8 for one task: a stored question, else the standard question; FOLD for merged-not-live
    work; None when nothing here waits on the human."""
    if task.get("question"):
        return _ask(task.get("ask_kind") or "decide", task["question"], task.get("answer_how"),
                    task.get("reply_code"), auto=False)
    if "awaiting_confirmation" in flags:
        return _ask("confirm", "The agent says this is done. Is it?",
                    "Press Confirm done, or tell your agent what is missing.", None)
    if "merged_not_live" in flags:
        return FOLD
    links = live_links(items)
    if "blocked_needs_input" in flags:
        card = next((i for i in links if i["source"] == "kanban" and effective_category(i) == "blocked"
                     and i.get("blocked_reason") == "needs_input"), None)
        if card:
            cid = card["external_id"]
            return _ask("decide", f"What should card {cid} do next?",
                        "Read the block reason on the card, then reply to your agent:", f"{cid}: <answer>",
                        url=card.get("url"))
    human = _human(task.get("waiting_on"))
    if human:
        prs = [i for i in links if i["source"] == "github" and link_state(i) == "open"]
        prs.sort(key=lambda i: not _human(i.get("waiting_on")))
        if prs:
            name = _pr_name(prs[0]["external_id"])
            return _ask("review", f"Merge PR {name}?", REPLY, f"merge {name}", url=prs[0].get("url"))
        card = next((i for i in links if i["source"] == "kanban" and effective_category(i) == "review"), None)
        if card:
            cid = card["external_id"]
            return _ask("review", f"Approve card {cid}?", REPLY, f"push {cid}", url=card.get("url"))
    if human or "blocked_needs_input" in flags:
        return _missing(task["key"])
    return None


def resolve_ask(task: dict, items: list[dict], flags: list[str], now: int):
    """The ask of one open task row, first match wins (rules 1-8): an ask dict, FOLD, or None.
    A task whose ask is not due yet stays under Later and out of its project's Release row."""
    nb = task.get("not_before")
    if nb is not None and nb > now:
        a = _computed(task, items, [f for f in flags if f != "merged_not_live"])
        if a is None:
            if "merged_not_live" not in flags:
                return None
            a = _missing(task["key"])
        return {**a, "ask_kind": "later"}
    return _computed(task, items, flags)


def _merged_links(items) -> list[dict]:
    out = [i for i in live_links(items) if i.get("merged_at") and not i.get("live_at")]
    return sorted(out, key=lambda i: (i["merged_at"], i["id"]))


def release_ask(name: str, project_key: str) -> dict:
    return _ask("release", f"Release {name} to its live branch?", REPLY, f"release {project_key.lower()}")


def release_rows(folded: list[dict], names: dict[str, str]) -> list[dict]:
    """One Release row per project over its folded tasks (load_tasks rows): their merged-not-live links,
    oldest first."""
    by_project: dict[str, list[dict]] = {}
    pids: dict[str, int] = {}
    for row in folded:
        pk = row["task"]["project_key"]
        pids[pk] = row["task"]["project_id"]
        by_project.setdefault(pk, []).extend(_merged_links(row["items"]))
    out = []
    for pk, links in by_project.items():
        if not links:
            continue
        links.sort(key=lambda i: (i["merged_at"], i["id"]))
        name = names.get(pk, pk)
        a = release_ask(name, pk)
        out.append({
            "kind": "release", "id": pids[pk], "ref": f"release:{pk}",
            "title": f"{name}: {len(links)} changes merged, not live",
            "project_key": pk, "epic_key": None, "url": None, "waiting_on": links[0].get("waiting_on"),
            "waiting_since": links[0]["merged_at"], "reasons": ["merged, not live"],
            **{k: v for k, v in a.items() if k != "url"},
            "context": ", ".join(i["title"] for i in links),
            "items": [{"ref": item_ref(i), "title": i["title"], "url": i["url"], "project_key": pk} for i in links],
        })
    return out


def _task_reasons(t, d) -> list[str]:
    reasons = []
    if _human(t["waiting_on"]):
        reasons.append("waiting on you")
    if "awaiting_confirmation" in d.flags:
        reasons.append("awaiting your confirmation")
    if "merged_not_live" in d.flags:
        reasons.append("merged, not live")
    if "blocked_needs_input" in d.flags:
        reasons.append("blocked: needs your input")
    return reasons


async def _project_names(repo) -> dict[str, str]:
    return {p["key"]: p["name"] for p in await repo.query("select key, name from projects")}


async def needs_you(repo, *, now, project_key=None) -> list[dict]:
    """Rows waiting on the human, each with its question (rules in docs/api.md), grouped by answer kind
    (ASK_ORDER), oldest first inside each group. Epic rows only for an epic's own human wait."""
    rows = []
    for row in await load_epics(repo, project_key=project_key):
        e, items = row["epic"], row["items"]
        d = _derive(row, now)
        if d.hidden or d.board_column in ("done", "canceled") or not _human(e["waiting_on"]):
            continue
        reasons = ["waiting on you"]
        if "awaiting_approval" in d.flags:
            reasons.append("awaiting your approval")
        a = (_ask("decide", e["question"], e["answer_how"], e["reply_code"], auto=False) if e.get("question")
             else _missing(e["key"]))
        rows.append({"kind": "epic", "id": e["id"], "ref": e["key"], "title": e["title"],
                     "project_key": e["project_key"], "epic_key": e["key"], "url": None,
                     "waiting_on": e["waiting_on"], "waiting_since": _waiting_since(e, items, row["tasks"]),
                     "reasons": reasons, **{k: v for k, v in a.items() if k != "url"},
                     "context": e["goal"], "items": None})
    th = await thresholds(repo)
    folded = []
    for row in await _shown_tasks(repo, project_key, now):
        t, d = row["task"], row["derived"]
        if d.status not in OPEN_TASK:
            continue
        reasons = _task_reasons(t, d)
        if not reasons:
            continue
        a = resolve_ask(t, row["items"], d.flags, now)
        if a == FOLD:
            folded.append(row)
            continue
        if a is None:
            continue
        v = _view(row, now, th)
        rows.append({"kind": "task", "id": t["id"], "ref": t["key"], "title": t["summary"],
                     "project_key": t["project_key"], "epic_key": t["epic_key"], "url": a["url"],
                     "waiting_on": t["waiting_on"], "waiting_since": v["waiting_since"], "reasons": reasons,
                     **{k: v for k, v in a.items() if k != "url"}, "context": t["description"], "items": None})
    if folded:
        rows += release_rows(folded, await _project_names(repo))
    kinds = ("epic", "task", "release")
    return sorted(rows, key=lambda r: (ASK_ORDER.index(r["ask_kind"]), r["waiting_since"],
                                       kinds.index(r["kind"]), r["id"]))


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
        if epic_stalled(e, items, row["tasks"], d, now, th):
            add("epic", e["id"], e["key"], e["title"], e["waiting_on"],
                _waiting_since(e, items, row["tasks"]), {})
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
    card = _card(e, row["items"], row["tasks"], d, now, th)
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
    out.update({k: t[k] for k in ("question", "answer_how", "reply_code", "ask_kind", "not_before")})
    epic = await repo.first("select next_step from epics where id = ?", (t["epic_id"],)) if t["epic_id"] else None
    out["epic_next_step"] = epic and epic["next_step"]
    out["ask"] = await _detail_ask(repo, row, now)
    out["links"] = [_link_entry(i, now, th) for i in row["items"]]
    events = await repo.query(
        "select * from events where (subject_type='task' and subject_id=?) "
        "or (subject_type='item' and subject_id in (select id from items where task_id = ?)) "
        "order by at desc, id desc limit 50", (t["id"], t["id"]))
    out["events"] = _events(events)
    return out


async def _detail_ask(repo, row, now):
    """The task's Needs you ask as its row shows it (a folded task gets its project's Release ask);
    None when the task is not waiting on the human."""
    t, d = row["task"], row["derived"]
    if d.status not in OPEN_TASK or not _task_reasons(t, d):
        return None
    a = resolve_ask(t, row["items"], d.flags, now)
    if a == FOLD:
        p = await repo.first("select name from projects where key = ?", (t["project_key"],))
        a = release_ask(p["name"], t["project_key"])
    return a and {k: v for k, v in a.items() if k != "url"}


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
