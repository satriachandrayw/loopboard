import pytest

from loopboard.db import Repo
from tests.fakes.d1 import FakeD1


@pytest.fixture
def repo():
    db = FakeD1()
    db.apply_migrations()
    return Repo(db)


@pytest.fixture
def make_app():
    from loopboard.app import build_app

    def _make(**kw):
        db = FakeD1()
        db.apply_migrations()
        app = build_app(db=db, **kw)
        return app, Repo(db)

    return _make


@pytest.fixture
def client_for():
    import httpx

    def _client(app):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    return _client
