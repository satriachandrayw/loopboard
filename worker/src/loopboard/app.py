import time

from fastapi import FastAPI, Request

from loopboard.auth import AccessConfig, AuthError, Principal, require, web_crypto_verify
from loopboard.db import Repo


def build_app(*, db=None, clock=None, access=None, jwks=None, verify_sig=None, fetch_certs=None) -> FastAPI:
    app = FastAPI()
    if db is not None:
        app.state.repo = Repo(db)
    app.state.clock = clock or time.time
    app.state.access = access
    app.state.jwks = jwks if jwks is not None else {}
    app.state.verify_sig = verify_sig
    app.state.fetch_certs = fetch_certs

    @app.get("/api/health")
    async def health(p: Principal = require("read")):
        return {"ok": True, "principal": p.name}

    from loopboard.routes import ingest as ingest_routes

    from loopboard.routes import writes as writes_routes

    app.include_router(ingest_routes.router)
    app.include_router(writes_routes.router)
    from loopboard.routes import reads as reads_routes

    app.include_router(reads_routes.router)
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


JWKS_REFETCH_SECONDS = 60


async def fetch_certs(team_domain: str) -> dict:
    """Production: fetch team certs (Workers runtime only). Returns kid -> JWK."""
    from pyodide.http import pyfetch

    resp = await pyfetch(f"https://{team_domain}/cdn-cgi/access/certs")
    if not resp.ok:
        raise AuthError("certs fetch failed")
    data = await resp.json()
    return {k["kid"]: k for k in data["keys"]}


async def get_jwks(request: Request, refresh: bool = False) -> dict:
    """kid -> JWK, cached on app.state. Fetches when empty or on refresh, at most
    once per 60 s (app clock). Any fetch/parse failure is an AuthError (401)."""
    state = request.app.state
    if state.jwks and not refresh:
        return state.jwks
    access = get_access(request)
    if access is None:
        return state.jwks
    now = get_now(request)
    last = getattr(state, "jwks_attempt_at", None)
    if last is not None and now - last < JWKS_REFETCH_SECONDS:
        return state.jwks
    state.jwks_attempt_at = now
    fetch = getattr(state, "fetch_certs", None) or fetch_certs
    try:
        table = await fetch(access.team_domain)
        if not isinstance(table, dict):
            raise AuthError("bad certs")
    except Exception as e:
        raise AuthError("certs unavailable") from e
    state.jwks = table
    return table
