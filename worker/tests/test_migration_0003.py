from tests.test_migration_0002 import seeded_0001

TABLES = ("projects", "epics", "items", "tasks", "events", "relations")


async def test_0003_adds_ask_fields_and_keeps_every_row():
    db, repo = await seeded_0001()
    db.apply_migrations(upto="0002_tasks.sql")
    before = {t: (await repo.first(f"select count(*) as n from {t}"))["n"] for t in TABLES}
    tasks_before = await repo.query("select * from tasks order by id")
    db.apply_migrations(upto="0003_ask_fields.sql")
    after = {t: (await repo.first(f"select count(*) as n from {t}"))["n"] for t in TABLES}
    assert before == after and before["tasks"] > 0
    tasks = await repo.query("select * from tasks order by id")
    for old, new in zip(tasks_before, tasks):
        assert {k: new[k] for k in old} == old
        assert all(new[k] is None for k in ("question", "answer_how", "reply_code", "ask_kind", "not_before"))
    epic = await repo.first("select * from epics order by id")
    assert all(epic[k] is None for k in ("question", "answer_how", "reply_code"))
