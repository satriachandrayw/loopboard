import re

from fastapi.routing import APIRoute


async def test_every_api_route_requires_credentials(make_app, client_for):
    app, _ = make_app()
    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/api/")]
    assert routes
    async with client_for(app) as c:
        for r in routes:
            path = r.path
            path = re.sub(r"\{[^}]+\}", "1", path)
            for m in r.methods - {"HEAD", "OPTIONS"}:
                resp = await c.request(m, path, json={})
                assert resp.status_code == 401, (m, r.path)


async def test_no_openapi_or_docs_routes(make_app, client_for):
    app, _ = make_app()
    async with client_for(app) as c:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await c.get(path)).status_code == 404, path
