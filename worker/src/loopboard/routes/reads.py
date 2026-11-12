from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from loopboard import reads
from loopboard.app import get_now, get_repo
from loopboard.auth import Principal, require

router = APIRouter()
Group = Literal["agent", "human", "source"]


@router.get("/api/projects")
async def projects(p: Principal = require("read"), repo=Depends(get_repo)):
    return await reads.projects(repo)


@router.get("/api/board")
async def board(project: str | None = None, waiting_on: Group | None = None,
                p: Principal = require("read"), repo=Depends(get_repo), now: int = Depends(get_now)):
    return await reads.board(repo, now=now, project_key=project, waiting_on=waiting_on)


@router.get("/api/needs-you")
async def needs_you(p: Principal = require("read"), repo=Depends(get_repo), now: int = Depends(get_now)):
    return await reads.needs_you(repo, now=now)


@router.get("/api/stalled")
async def stalled(waiting_on: Group | None = None, p: Principal = require("read"),
                  repo=Depends(get_repo), now: int = Depends(get_now)):
    return await reads.stalled(repo, now=now, waiting_on=waiting_on)


@router.get("/api/unfiled")
async def unfiled(p: Principal = require("read"), repo=Depends(get_repo), now: int = Depends(get_now)):
    return await reads.unfiled(repo, now=now)


@router.get("/api/epics/{key}")
async def epic_detail(key: str, p: Principal = require("read"), repo=Depends(get_repo),
                      now: int = Depends(get_now)):
    out = await reads.epic_detail(repo, key=key, now=now)
    if out is None:
        raise HTTPException(404, f"epic {key} not found")
    return out
