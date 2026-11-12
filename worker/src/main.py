from fastapi import FastAPI, Request
from workers import asgi

from loopboard import __version__
from loopboard.db import Repo

app = FastAPI()


@app.get("/api/probe")
async def probe():
    return {"version": __version__}


# TEMPORARY (Task 3 removes): real-runtime D1 probe.
@app.get("/api/probe/db")
async def probe_db(request: Request):
    import time

    repo = Repo(request.scope["env"].DB)
    k = str(int(time.time() * 1000))
    sql = "insert into projects(key, name, created_at) values (?, ?, ?)"
    await repo.batch([(sql, ("P" + k, "probe", 1)), (sql, ("Q" + k, "probe", 2))])
    rid = await repo.execute(sql, ("R" + k, "probe", 3))
    nul = await repo.execute(
        "insert into api_tokens(name, token_hash, scopes, source, created_at) values (?,?,?,?,?)",
        ("t" + k, "h" + k, "read", None, 1),
    )
    row = await repo.first("select source from api_tokens where id = ?", (nul,))
    return {"batch": "ok", "last_row_id": rid, "null_roundtrip": row}


class Default(asgi.entrypoint(app)):
    pass
