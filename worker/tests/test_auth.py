import base64
import json
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import Depends

from loopboard.auth import AccessConfig, hash_token, new_token, require

NOW = 1_800_000_000
ACCESS = AccessConfig("team.example.cloudflareaccess.com", "aud123")


async def add_token(repo, name="t", scopes="read", source=None, revoked=None):
    token, h = new_token()
    await repo.execute(
        "insert into api_tokens(name, token_hash, scopes, source, created_at, revoked_at) values (?,?,?,?,?,?)",
        (name, h, scopes, source, 1, revoked),
    )
    return token


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


async def test_bearer_token_authenticates_with_its_scopes(make_app, client_for):
    app, repo = make_app()
    t = await add_token(repo, name="bot")
    async with client_for(app) as c:
        r = await c.get("/api/health", headers=bearer(t))
    assert r.status_code == 200
    assert r.json() == {"ok": True, "principal": "bot"}


async def test_unknown_bearer_is_401(make_app, client_for):
    app, _ = make_app()
    async with client_for(app) as c:
        assert (await c.get("/api/health", headers=bearer("lb_nope"))).status_code == 401


async def test_revoked_token_is_401(make_app, client_for):
    app, repo = make_app()
    t = await add_token(repo, revoked=5)
    async with client_for(app) as c:
        assert (await c.get("/api/health", headers=bearer(t))).status_code == 401


async def test_read_token_cannot_use_ingest_scope(make_app, client_for):
    app, repo = make_app()

    @app.get("/api/only-ingest")
    async def only(p=require("ingest")):
        return {}

    t = await add_token(repo, scopes="read")
    async with client_for(app) as c:
        assert (await c.get("/api/only-ingest", headers=bearer(t))).status_code == 403


async def test_token_bound_to_source_is_recorded(make_app, client_for):
    app, repo = make_app()

    @app.get("/api/who")
    async def who(p=require("read")):
        return {"source": p.source, "kind": p.kind}

    t = await add_token(repo, source="kanban")
    async with client_for(app) as c:
        r = await c.get("/api/who", headers=bearer(t))
    assert r.json() == {"source": "kanban", "kind": "token"}


async def test_token_stored_only_as_hash(make_app):
    _, repo = make_app()
    t = await add_token(repo, name="x")
    row = await repo.first("select * from api_tokens where name = 'x'")
    assert row["token_hash"] == hash_token(t)
    assert all(t not in str(v) for v in row.values())


async def test_forged_access_header_without_jwt_is_401(make_app, client_for):
    app, _ = make_app(access=ACCESS)
    async with client_for(app) as c:
        r = await c.get("/api/health", headers={"Cf-Access-Authenticated-User-Email": "owner@example.com"})
    assert r.status_code == 401


# ---- Access JWT -----------------------------------------------------------

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _int_b64(n: int) -> str:
    return b64(n.to_bytes((n.bit_length() + 7) // 8, "big"))


def jwk_of(key):
    pn = key.public_key().public_numbers()
    return {"kty": "RSA", "kid": "k1", "n": _int_b64(pn.n), "e": _int_b64(pn.e)}


def sign(claims, key=KEY, kid="k1", alg="RS256"):
    h = b64(json.dumps({"alg": alg, "kid": kid}).encode())
    p = b64(json.dumps(claims).encode())
    sig = key.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{h}.{p}.{b64(sig)}"


def rsa_verify(signing_input, signature, jwk):
    def d(s):
        return int.from_bytes(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)), "big")

    pub = rsa.RSAPublicNumbers(d(jwk["e"]), d(jwk["n"])).public_key()
    try:
        pub.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:
        return False


def claims(**kw):
    c = {"iss": f"https://{ACCESS.team_domain}", "aud": [ACCESS.aud], "exp": NOW + 600, "email": "owner@example.com"}
    c.update(kw)
    return c


def access_app(make_app, access=ACCESS):
    return make_app(access=access, jwks={"k1": jwk_of(KEY)}, verify_sig=rsa_verify, clock=lambda: NOW)


async def test_valid_access_jwt_grants_all_scopes(make_app, client_for):
    app, _ = access_app(make_app)

    @app.get("/api/who")
    async def who(p=require("ingest")):
        return {"name": p.name, "kind": p.kind, "scopes": sorted(p.scopes), "source": p.source}

    async with client_for(app) as c:
        r = await c.get("/api/who", headers={"Cf-Access-Jwt-Assertion": sign(claims())})
    assert r.status_code == 200
    assert r.json() == {
        "name": "owner@example.com",
        "kind": "access",
        "scopes": ["ingest", "read", "write"],
        "source": None,
    }


async def test_access_jwt_wrong_audience_is_401(make_app, client_for):
    app, _ = access_app(make_app)
    async with client_for(app) as c:
        r = await c.get("/api/health", headers={"Cf-Access-Jwt-Assertion": sign(claims(aud=["other"]))})
    assert r.status_code == 401


async def test_access_jwt_expired_is_401(make_app, client_for):
    app, _ = access_app(make_app)
    async with client_for(app) as c:
        r = await c.get("/api/health", headers={"Cf-Access-Jwt-Assertion": sign(claims(exp=NOW - 1))})
    assert r.status_code == 401


async def test_access_jwt_bad_signature_is_401(make_app, client_for):
    app, _ = access_app(make_app)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    async with client_for(app) as c:
        r = await c.get("/api/health", headers={"Cf-Access-Jwt-Assertion": sign(claims(), key=other)})
    assert r.status_code == 401


async def test_access_disabled_ignores_valid_jwt(make_app, client_for):
    app, _ = access_app(make_app, access=None)
    async with client_for(app) as c:
        r = await c.get("/api/health", headers={"Cf-Access-Jwt-Assertion": sign(claims())})
    assert r.status_code == 401


def test_make_token_prints_hash_not_token():
    script = Path(__file__).resolve().parents[1] / "scripts" / "make_token.py"
    out = subprocess.run(
        [sys.executable, str(script), "--name", "bot", "--scopes", "ingest", "--source", "kanban"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    token = out[0].removeprefix("TOKEN=")
    assert token.startswith("lb_")
    sql = "\n".join(out[1:])
    assert "INSERT INTO api_tokens" in sql
    assert hash_token(token) in sql
    assert token not in sql


# ---- negative JWT cases and JWKS fetching ---------------------------------

def raw_jwt(header, payload, sig=b"x"):
    h = b64(json.dumps(header).encode()) if not isinstance(header, bytes) else b64(header)
    p = b64(json.dumps(payload).encode()) if not isinstance(payload, bytes) else b64(payload)
    return f"{h}.{p}.{b64(sig)}"


async def status_for(make_app, client_for, jwt, **kw):
    app, _ = access_app(make_app)
    async with client_for(app) as c:
        return (await c.get("/api/health", headers={"Cf-Access-Jwt-Assertion": jwt})).status_code


async def test_access_jwt_negative_cases_are_401(make_app, client_for):
    good = claims()
    cases = [
        sign(claims(iss="https://evil.example.com")),
        raw_jwt({"alg": "none", "kid": "k1"}, good),
        raw_jwt({"alg": "HS256", "kid": "k1"}, good),
        sign(good, kid="nope"),
        raw_jwt({"alg": "RS256", "kid": ["k1"]}, good),
        "a.b",
        "a.b.c.d",
        "!!!.@@@.###",
        raw_jwt(b"not json", good),
        sign({k: v for k, v in good.items() if k != "email"}),
    ]
    for jwt in cases:
        assert await status_for(make_app, client_for, jwt) == 401, jwt


def fake_fetch(keys, calls):
    async def fetch(team):
        calls.append(team)
        if keys is None:
            raise RuntimeError("down")
        return keys

    return fetch


async def test_jwks_fetched_when_empty(make_app, client_for):
    calls = []
    app, _ = make_app(
        access=ACCESS, verify_sig=rsa_verify, clock=lambda: NOW, fetch_certs=fake_fetch({"k1": jwk_of(KEY)}, calls)
    )
    async with client_for(app) as c:
        r = await c.get("/api/health", headers={"Cf-Access-Jwt-Assertion": sign(claims())})
        r2 = await c.get("/api/health", headers={"Cf-Access-Jwt-Assertion": sign(claims())})
    assert (r.status_code, r2.status_code) == (200, 200)
    assert calls == [ACCESS.team_domain]


async def test_jwks_fetch_failure_is_401_but_bearer_still_works(make_app, client_for):
    calls = []
    app, repo = make_app(access=ACCESS, verify_sig=rsa_verify, clock=lambda: NOW, fetch_certs=fake_fetch(None, calls))
    t = await add_token(repo)
    async with client_for(app) as c:
        r = await c.get("/api/health", headers={"Cf-Access-Jwt-Assertion": sign(claims())})
        r2 = await c.get("/api/health", headers={**bearer(t), "Cf-Access-Jwt-Assertion": sign(claims())})
    assert r.status_code == 401
    assert r2.status_code == 200
    assert len(calls) == 1


async def test_jwks_refetch_on_unknown_kid_throttled(make_app, client_for):
    calls = []
    now = [NOW]
    new_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    keys = {"k1": jwk_of(KEY), "k2": {**jwk_of(new_key), "kid": "k2"}}
    app, _ = make_app(
        access=ACCESS, jwks={"k1": jwk_of(KEY)}, verify_sig=rsa_verify, clock=lambda: now[0],
        fetch_certs=fake_fetch(keys, calls),
    )
    h = {"Cf-Access-Jwt-Assertion": sign(claims(), key=new_key, kid="k2")}
    async with client_for(app) as c:
        assert (await c.get("/api/health", headers=h)).status_code == 200
        assert len(calls) == 1
        bad = {"Cf-Access-Jwt-Assertion": sign(claims(), kid="k3")}
        assert (await c.get("/api/health", headers=bad)).status_code == 401  # throttled
        assert len(calls) == 1
        now[0] += 61
        assert (await c.get("/api/health", headers=bad)).status_code == 401
        assert len(calls) == 2


def test_make_token_rejects_unknown_scope():
    script = Path(__file__).resolve().parents[1] / "scripts" / "make_token.py"
    r = subprocess.run([sys.executable, str(script), "--name", "b", "--scopes", "admin"], capture_output=True, text=True)
    assert r.returncode != 0


def _mk(*args):
    script = Path(__file__).resolve().parents[1] / "scripts" / "make_token.py"
    return subprocess.run([sys.executable, str(script), "--name", "b", *args], capture_output=True, text=True)


def test_make_token_ingest_requires_source():
    r = _mk("--scopes", "ingest")
    assert r.returncode != 0 and "TOKEN=" not in r.stdout


def test_make_token_source_refused_with_read_or_write():
    for scopes in ("read", "write", "read,write", "ingest,read"):
        r = _mk("--scopes", scopes, "--source", "kanban")
        assert r.returncode != 0 and "TOKEN=" not in r.stdout, scopes


async def test_invalid_bearer_falls_through_to_valid_access_jwt(make_app, client_for):
    app, _ = access_app(make_app)
    async with client_for(app) as c:
        r = await c.get("/api/health", headers={**bearer("lb_stale"), "Cf-Access-Jwt-Assertion": sign(claims())})
        assert r.status_code == 200
        bad = {**bearer("lb_stale"), "Cf-Access-Jwt-Assertion": sign(claims(exp=NOW - 1))}
        assert (await c.get("/api/health", headers=bad)).status_code == 401
        assert (await c.get("/api/health", headers=bearer("lb_stale"))).status_code == 401


async def test_invalid_bearer_does_not_use_access_when_disabled(make_app, client_for):
    app, _ = access_app(make_app, access=None)
    async with client_for(app) as c:
        r = await c.get("/api/health", headers={**bearer("lb_stale"), "Cf-Access-Jwt-Assertion": sign(claims())})
    assert r.status_code == 401


async def test_access_jwt_not_yet_valid_is_401_with_60s_leeway(make_app, client_for):
    app, _ = access_app(make_app)
    async with client_for(app) as c:
        ok = {"Cf-Access-Jwt-Assertion": sign(claims(nbf=NOW + 60))}
        assert (await c.get("/api/health", headers=ok)).status_code == 200
        bad = {"Cf-Access-Jwt-Assertion": sign(claims(nbf=NOW + 61))}
        assert (await c.get("/api/health", headers=bad)).status_code == 401
        junk = {"Cf-Access-Jwt-Assertion": sign(claims(nbf="soon"))}
        assert (await c.get("/api/health", headers=junk)).status_code == 401


async def test_verifier_exception_is_401_not_500(make_app, client_for):
    def boom(signing_input, signature, jwk):
        raise ValueError("unsupported key")

    app, _ = make_app(access=ACCESS, jwks={"k1": {"kty": "EC"}}, verify_sig=boom, clock=lambda: NOW)
    async with client_for(app) as c:
        r = await c.get("/api/health", headers={"Cf-Access-Jwt-Assertion": sign(claims())})
    assert r.status_code == 401
