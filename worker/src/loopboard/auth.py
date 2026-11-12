"""Bearer tokens, Cloudflare Access JWT verification and scope guard."""

import base64
import hashlib
import inspect
import json
import secrets
from dataclasses import dataclass
from typing import Callable, Literal

from fastapi import Depends, HTTPException, Request

ALL_SCOPES = frozenset({"ingest", "read", "write"})


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    name: str
    kind: Literal["token", "access"]
    scopes: frozenset[str]
    source: str | None = None


@dataclass(frozen=True)
class AccessConfig:
    team_domain: str
    aud: str


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    token = "lb_" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    return token, hash_token(token)


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


async def verify_access_jwt(
    token: str, access: AccessConfig, *, jwks: dict, now: int, verify_sig: Callable
) -> dict:
    """jwks maps kid -> JWK. verify_sig may be sync or async."""
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("malformed jwt")
    try:
        header = json.loads(_b64d(parts[0]))
        claims = json.loads(_b64d(parts[1]))
        signature = _b64d(parts[2])
    except Exception as e:
        raise AuthError("malformed jwt") from e
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise AuthError("malformed jwt")
    if header.get("alg") != "RS256":
        raise AuthError("bad alg")
    jwk = jwks.get(header.get("kid"))
    if jwk is None:
        raise AuthError("unknown kid")
    if claims.get("iss") != f"https://{access.team_domain}":
        raise AuthError("bad issuer")
    aud = claims.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if access.aud not in auds:
        raise AuthError("bad audience")
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp <= now:
        raise AuthError("expired")
    ok = verify_sig(f"{parts[0]}.{parts[1]}".encode(), signature, jwk)
    if inspect.isawaitable(ok):
        ok = await ok
    if not ok:
        raise AuthError("bad signature")
    return claims


async def web_crypto_verify(signing_input: bytes, signature: bytes, jwk: dict) -> bool:
    """Production RS256 verification through WebCrypto (Workers runtime only)."""
    from js import Object, Uint8Array, crypto
    from pyodide.ffi import to_js

    key = await crypto.subtle.importKey(
        "jwk",
        to_js(jwk, dict_converter=Object.fromEntries),
        to_js({"name": "RSASSA-PKCS1-v1_5", "hash": "SHA-256"}, dict_converter=Object.fromEntries),
        False,
        to_js(["verify"]),
    )
    return bool(
        await crypto.subtle.verify(
            "RSASSA-PKCS1-v1_5", key, Uint8Array.new(to_js(list(signature))), Uint8Array.new(to_js(list(signing_input)))
        )
    )


async def authenticate(request: Request, repo, *, access, jwks, verify_sig, now) -> Principal:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        row = await repo.first(
            "select name, scopes, source from api_tokens where token_hash = ? and revoked_at is null",
            (hash_token(token),),
        )
        if row is None:
            raise AuthError("invalid token")
        scopes = frozenset(s.strip() for s in row["scopes"].split(",") if s.strip())
        return Principal(row["name"], "token", scopes, row["source"])
    jwt = request.headers.get("cf-access-jwt-assertion")
    if access is not None and jwt:
        if verify_sig is None:
            raise AuthError("no verifier")
        claims = await verify_access_jwt(jwt, access, jwks=jwks, now=now, verify_sig=verify_sig)
        email = claims.get("email")
        if not email:
            raise AuthError("no email claim")
        return Principal(email, "access", ALL_SCOPES, None)
    raise AuthError("unauthenticated")


def require(scope: str):
    async def dep(request: Request) -> Principal:
        from loopboard import app as appmod

        try:
            p = await authenticate(
                request,
                appmod.get_repo(request),
                access=appmod.get_access(request),
                jwks=await appmod.get_jwks(request),
                verify_sig=appmod.get_verify_sig(request),
                now=appmod.get_now(request),
            )
        except AuthError:
            raise HTTPException(401, "unauthorized") from None
        if scope not in p.scopes:
            raise HTTPException(403, "forbidden")
        request.state.principal = p
        return p

    return Depends(dep)
