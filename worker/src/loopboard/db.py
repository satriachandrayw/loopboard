"""The only module that touches D1.

Works with the real Workers D1 binding (JS objects through Pyodide) and with
the in-memory fake in tests/fakes/d1.py.
"""

# Runtime notes (verified with pywrangler dev): the `env.DB` binding in the
# Python Workers SDK is an RPC wrapper (workers/rpc.py). It converts call
# arguments itself (None -> JS null, wrapped statements -> raw JS objects, lists
# -> arrays) and converts results back to Python (dict/list). So no manual
# jsnull/to_js handling is needed here; Python None is passed through as-is.


def _py(x):
    return x.to_py() if hasattr(x, "to_py") else x


def _rows(res) -> list[dict]:
    r = res.results
    r = r.to_py() if hasattr(r, "to_py") else list(r)
    return [dict(x) for x in r]


def _meta_get(meta, key):
    meta = _py(meta)
    if isinstance(meta, dict):
        return meta.get(key)
    try:
        return meta[key]
    except Exception:
        return getattr(meta, key, None)


class Repo:
    def __init__(self, db):
        self.db = db

    def _stmt(self, sql, args):
        return self.db.prepare(sql).bind(*args)

    async def first(self, sql, args=()):
        rows = await self.query(sql, args)
        return rows[0] if rows else None

    async def query(self, sql, args=()):
        return _rows(await self._stmt(sql, args).all())

    async def execute(self, sql, args=()) -> int:
        res = await self._stmt(sql, args).run()
        meta = getattr(res, "meta", None)
        rid = _meta_get(meta, "last_row_id") if meta is not None else None
        if rid is None:
            # Fallback if the D1 Python binding exposes no meta.last_row_id.
            row = await self.first("select last_insert_rowid() as id")
            rid = row["id"] if row else None
        return rid

    async def batch(self, stmts) -> list:
        """Run (sql, args) statements in one transaction; any failure rolls back all.

        Returns meta.changes per statement (None where the binding gives none)."""
        bound = [self._stmt(sql, args) for sql, args in stmts]
        results = _py(await self.db.batch(bound))
        out = []
        for res in results if results is not None else []:
            res = _py(res)
            meta = res.get("meta") if isinstance(res, dict) else getattr(res, "meta", None)
            out.append(_meta_get(meta, "changes") if meta is not None else None)
        return out
