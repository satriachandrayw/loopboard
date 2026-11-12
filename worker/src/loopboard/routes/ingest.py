from fastapi import APIRouter, Depends, HTTPException

from loopboard.app import get_now, get_repo
from loopboard.auth import Principal, require
from loopboard.ingest import ingest_items
from loopboard.model import IngestIn, ValidationError

router = APIRouter()


@router.post("/api/ingest")
async def ingest(body: IngestIn, p: Principal = require("ingest"),
                 repo=Depends(get_repo), now: int = Depends(get_now)):
    if p.source is not None and p.source != body.source:
        raise HTTPException(403, "token is bound to another source")
    try:
        return await ingest_items(repo, source=body.source, items=body.items,
                                  actor=p.name, via="ingest", now=now)
    except ValidationError as e:
        raise HTTPException(422, str(e)) from None
