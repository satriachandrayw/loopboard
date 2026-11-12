import pytest

from loopboard.db import Repo


async def test_migration_creates_tables(repo):
    rows = await repo.query("select name from sqlite_master")
    names = {r["name"] for r in rows}
    assert {"projects", "epics", "items", "relations", "events", "api_tokens", "sources"} <= names


async def test_events_are_append_only(repo):
    await repo.execute(
        "insert into events(at, actor, via, subject_type, subject_id, kind, payload)"
        " values (1, 'human:owner', 'api', 'epic', 1, 'created', '{}')"
    )
    with pytest.raises(Exception, match="append-only"):
        await repo.execute("update events set kind = 'x'")
    with pytest.raises(Exception, match="append-only"):
        await repo.execute("delete from events")


async def test_batch_is_one_transaction(repo):
    sql = "insert into projects(key, name, created_at) values (?, ?, ?)"
    with pytest.raises(Exception):
        await repo.batch([(sql, ("DEMO", "Demo", 1)), (sql, ("DEMO", "Dup", 2))])
    assert await repo.query("select * from projects") == []


async def test_first_returns_none_when_missing(repo):
    assert await repo.first("select * from projects where key = ?", ("NOPE",)) is None


async def test_repo_reads_plain_list_results():
    class Res:
        results = [{"a": 1}, {"a": 2}]

    class Stmt:
        def bind(self, *a):
            return self

        async def all(self):
            return Res()

    class Db:
        def prepare(self, sql):
            return Stmt()

    assert await Repo(Db()).query("select a") == [{"a": 1}, {"a": 2}]


async def test_execute_returns_last_row_id(repo):
    n = await repo.execute("insert into projects(key, name, created_at) values ('A','A',1)")
    m = await repo.execute("insert into projects(key, name, created_at) values ('B','B',1)")
    assert m == n + 1


async def test_none_args_round_trip(repo):
    await repo.execute("insert into projects(key, name, created_at) values (?, ?, ?)", ("A", "A", 1))
    await repo.execute(
        "insert into sources(name, updated_at) values (?, ?)", ("s", 1)
    )
    await repo.execute(
        "insert into api_tokens(name, token_hash, scopes, source, created_at) values (?,?,?,?,?)",
        ("t", "h", "read", None, 1),
    )
    row = await repo.first("select source from api_tokens where name = 't'")
    assert row == {"source": None}
