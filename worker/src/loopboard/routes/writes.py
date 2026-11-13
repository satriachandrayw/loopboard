from fastapi import APIRouter, Depends, HTTPException, Request, Response

from loopboard import reads, writes
from loopboard.app import get_now, get_repo
from loopboard.auth import Principal, require
from loopboard.model import (DeployedIn, EpicIn, EpicPatch, FilingIn, LinkIn, MergeIn, ProjectIn, RelationIn,
                             SourceIn, TaskIn, TaskPatch, TaskStatusIn, ValidationError, parse_ts)

router = APIRouter()
SOURCE_NAME = r"[a-z][a-z0-9_-]{1,31}"


async def _card(repo, key: str, now: int) -> dict:
    """The epic as GET /api/epics/{key} shows it: derived `column` only, no stored column fields."""
    return (await reads.epic_detail(repo, key=key, now=now))["epic"]


async def _run(coro):
    try:
        return await coro
    except writes.NotFound as e:
        raise HTTPException(404, str(e)) from None
    except writes.Conflict as e:
        raise HTTPException(409, str(e)) from None
    except writes.Forbidden as e:
        raise HTTPException(403, str(e)) from None
    except ValidationError as e:
        raise HTTPException(422, str(e)) from None


@router.post("/api/projects", status_code=201)
async def create_project(body: ProjectIn, p: Principal = require("write"),
                         repo=Depends(get_repo), now: int = Depends(get_now)):
    return await _run(writes.create_project(repo, key=body.key, name=body.name, actor=p.name, now=now))


@router.post("/api/projects/{project_key}/epics", status_code=201)
async def create_epic(project_key: str, body: EpicIn, p: Principal = require("write"),
                      repo=Depends(get_repo), now: int = Depends(get_now)):
    e = await _run(writes.create_epic(repo, project_key=project_key, body=body, actor=p.name, now=now))
    return await _card(repo, e["key"], now)


@router.patch("/api/epics/{key}")
async def patch_epic(key: str, body: EpicPatch, p: Principal = require("write"),
                     repo=Depends(get_repo), now: int = Depends(get_now)):
    e = await _run(writes.patch_epic(repo, key=key, changes=body, actor=p.name, now=now))
    return await _card(repo, e["key"], now)


def _json_only(request: Request):
    # No body, so require a JSON content type: a cross-site HTML form cannot send one
    # without a CORS preflight, so the Access cookie cannot be ridden here (CSRF).
    ctype = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if ctype != "application/json":
        raise HTTPException(415, "Content-Type must be application/json")


@router.post("/api/epics/{key}/confirm-done")
async def confirm_done(key: str, request: Request, p: Principal = require("write"),
                       repo=Depends(get_repo), now: int = Depends(get_now)):
    _json_only(request)
    e = await _run(writes.confirm_done(repo, key=key, actor=p.name, now=now))
    return await _card(repo, e["key"], now)


@router.post("/api/items/{item_id}/filing")
async def set_filing(item_id: int, body: FilingIn, p: Principal = require("write"),
                     repo=Depends(get_repo), now: int = Depends(get_now)):
    return await _run(writes.set_filing(repo, item_id=item_id, body=body, actor=p.name, now=now))


@router.post("/api/items/{item_id}/deployed")
async def deployed(item_id: int, body: DeployedIn, p: Principal = require("write"),
                   repo=Depends(get_repo), now: int = Depends(get_now)):
    return await _run(writes.mark_deployed(repo, item_id=item_id, live_at=parse_ts(body.live_at),
                                           actor=p.name, now=now))


@router.post("/api/relations", status_code=201)
async def create_relation(body: RelationIn, p: Principal = require("write"),
                          repo=Depends(get_repo), now: int = Depends(get_now)):
    return await _run(writes.create_relation(repo, body=body, actor=p.name, now=now))


@router.delete("/api/relations/{relation_id}", status_code=204)
async def delete_relation(relation_id: int, p: Principal = require("write"),
                          repo=Depends(get_repo), now: int = Depends(get_now)):
    await _run(writes.delete_relation(repo, relation_id=relation_id, actor=p.name, now=now))
    return Response(status_code=204)


@router.put("/api/sources/{name}")
async def put_source(name: str, body: SourceIn, p: Principal = require("write"),
                     repo=Depends(get_repo), now: int = Depends(get_now)):
    import re

    if not re.fullmatch(SOURCE_NAME, name):
        raise HTTPException(422, "invalid source name")
    return await _run(writes.put_source(repo, name=name, stall_hours=body.stall_hours, actor=p.name, now=now))


async def _task_card(repo, key: str, now: int) -> dict:
    return await reads.task_card(repo, key=key, now=now)


@router.post("/api/projects/{project_key}/tasks", status_code=201)
async def create_task(project_key: str, body: TaskIn, p: Principal = require("write"),
                      repo=Depends(get_repo), now: int = Depends(get_now)):
    t = await _run(writes.create_task(repo, project_key=project_key, body=body, actor=p.name, now=now))
    return await _task_card(repo, t["key"], now)


@router.patch("/api/tasks/{key}")
async def patch_task(key: str, body: TaskPatch, p: Principal = require("write"),
                     repo=Depends(get_repo), now: int = Depends(get_now)):
    t = await _run(writes.patch_task(repo, key=key, changes=body, actor=p.name, now=now))
    return await _task_card(repo, t["key"], now)


@router.post("/api/tasks/{key}/status")
async def set_task_status(key: str, body: TaskStatusIn, p: Principal = require("write"),
                          repo=Depends(get_repo), now: int = Depends(get_now)):
    t = await _run(writes.set_task_status(repo, key=key, status=body.status, actor=p.name,
                                          human=p.is_human, now=now))
    return await _task_card(repo, t["key"], now)


@router.post("/api/tasks/{key}/confirm-done")
async def confirm_task_done(key: str, request: Request, p: Principal = require("write"),
                            repo=Depends(get_repo), now: int = Depends(get_now)):
    _json_only(request)
    t = await _run(writes.confirm_task_done(repo, key=key, actor=p.name, human=p.is_human, now=now))
    return await _task_card(repo, t["key"], now)


@router.post("/api/tasks/{key}/merge")
async def merge_tasks(key: str, body: MergeIn, p: Principal = require("write"),
                      repo=Depends(get_repo), now: int = Depends(get_now)):
    t = await _run(writes.merge_tasks(repo, key=key, into=body.into, actor=p.name, now=now))
    return await _task_card(repo, t["key"], now)


@router.post("/api/items/{item_id}/link")
async def link_item(item_id: int, body: LinkIn, p: Principal = require("write"),
                    repo=Depends(get_repo), now: int = Depends(get_now)):
    return await _run(writes.link_item(repo, item_id=item_id, task_key=body.task_key, actor=p.name, now=now))


@router.post("/api/items/{item_id}/unlink")
async def unlink_item(item_id: int, p: Principal = require("write"),
                      repo=Depends(get_repo), now: int = Depends(get_now)):
    return await _run(writes.unlink_item(repo, item_id=item_id, actor=p.name, now=now))
