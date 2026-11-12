import time

from fastapi import FastAPI, Request

from loopboard.auth import AccessConfig, Principal, require, web_crypto_verify
from loopboard.db import Repo


def build_app(*, db=None, clock=None, access=None, jwks=None, verify_sig=None) -> FastAPI:
    app = FastAPI()
    if db is not None:
        app.state.repo = Repo(db)
    app.state.clock = clock or time.time
    app.state.access = access
    app.state.jwks = jwks if jwks is not None else {}
    app.state.verify_sig = verify_sig

    @app.get("/api/health")
    async def health(p: Principal = require("read")):
        return {"ok": True, "principal": p.name}

    return app


def get_repo(request: Request) -> Repo:
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        repo = Repo(request.scope["env"].DB)
    return repo


def get_now(request: Request) -> int:
    return int(request.app.state.clock())


def get_access(request: Request):
    access = getattr(request.app.state, "access", None)
    if access is not None:
        return access
    env = request.scope.get("env")
    team = getattr(env, "ACCESS_TEAM_DOMAIN", "") if env is not None else ""
    aud = getattr(env, "ACCESS_AUD", "") if env is not None else ""
    return AccessConfig(team, aud) if team and aud else None


def get_verify_sig(request: Request):
    return getattr(request.app.state, "verify_sig", None) or web_crypto_verify


async def get_jwks(request: Request) -> dict:
    """kid -> JWK. Production gap-fill: fetched once from the team certs URL and cached."""
    state = request.app.state
    if state.jwks:
        return state.jwks
    access = get_access(request)
    if access is None or not request.headers.get("cf-access-jwt-assertion"):
        return {}
    from pyodide.http import pyfetch  # Workers runtime only

    resp = await pyfetch(f"https://{access.team_domain}/cdn-cgi/access/certs")
    data = await resp.json()
    state.jwks = {k["kid"]: k for k in data.get("keys", [])}
    return state.jwks
