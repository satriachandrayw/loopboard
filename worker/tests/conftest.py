import pytest

from loopboard.db import Repo
from tests.fakes.d1 import FakeD1


@pytest.fixture
def repo():
    db = FakeD1()
    db.apply_migrations()
    return Repo(db)
