"""In-memory stand-in for the Workers D1 binding, backed by stdlib sqlite3.

Implements the same prepare/bind/all/first/run/batch surface. Results mimic
D1: ``all()`` returns an object with ``.results.to_py()`` and ``.meta``.
"""

import sqlite3

try:
    from pyodide.ffi import jsnull
except ImportError:
    jsnull = object()
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def to_py(self):
        return [dict(r) for r in self._rows]


class _Result:
    def __init__(self, rows, last_row_id=None, changes=0):
        self.results = _Rows(rows)
        self.meta = {"last_row_id": last_row_id, "changes": changes}
        self.success = True


class _Stmt:
    def __init__(self, db, sql):
        self._db = db
        self.sql = sql
        self.args = ()

    def bind(self, *args):
        s = _Stmt(self._db, self.sql)
        s.args = tuple(None if a is jsnull else a for a in args)  # D1 maps JS null to SQL NULL
        return s

    def _exec(self):
        cur = self._db._conn.execute(self.sql, self.args)
        rows = cur.fetchall() if cur.description else []
        return _Result(rows, cur.lastrowid, cur.rowcount)

    async def all(self):
        return self._db._run_one(self)

    async def run(self):
        return self._db._run_one(self)

    async def first(self):
        res = self._db._run_one(self)
        rows = res.results.to_py()
        return rows[0] if rows else None


class FakeD1:
    def __init__(self):
        self._conn = sqlite3.connect(":memory:", isolation_level=None)
        self._conn.row_factory = sqlite3.Row

    def prepare(self, sql):
        return _Stmt(self, sql)

    def _run_one(self, stmt):
        return stmt._exec()

    async def batch(self, stmts):
        out = []
        self._conn.execute("begin")
        try:
            for s in stmts:
                out.append(s._exec())
        except Exception:
            self._conn.execute("rollback")
            raise
        self._conn.execute("commit")
        return out

    def apply_migrations(self):
        for f in sorted(MIGRATIONS.glob("*.sql")):
            self._conn.executescript(f.read_text())
