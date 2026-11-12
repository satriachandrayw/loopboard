# Loopboard v1a Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Loopboard v1a: projects, epics, items, relations and an append-only event log in a Python Worker (FastAPI + D1), with the five-column board, stall flags, five screens, and push connectors for Hermes Kanban and GitHub PRs, runnable locally.

**Architecture:** One monorepo. All D1 SQL sits behind one `Repo` class, so logic runs under pytest against an in-memory SQLite fake. Pure functions compute column, flags and stall from rows. Each write appends events and updates current rows in one `Repo.batch`. The React app builds into `worker/public` and is served by the same Worker. `connectors/` is a host-side push runner that posts batches of at most 100 items to `/api/ingest` with a per-connector bearer token.

**Tech Stack:** Python 3.13+, uv 0.13.4+, FastAPI, pydantic, Cloudflare Python Workers (pywrangler), D1, pytest + pytest-asyncio + httpx, cryptography (tests only), React + TypeScript, Vite, Vitest + Testing Library + jsdom, GitHub Actions.

**Spec:** `docs/design.md`

## Global Constraints

Project-wide requirements. Every task implicitly includes them.

- Repo `satriachandrayw/loopboard`. Monorepo: `worker/` (Python FastAPI on Cloudflare Workers + D1), `web/` (React + TypeScript, Vite, built into worker/public), `connectors/` (Python runner package `loopboard_connectors`, CLI `loopboard sync <connector>`), `docs/`. The repo already exists; work on the card's branch, never `git init`.
- Pins uv 0.13.4 or newer (`[tool.uv] required-version = ">=0.13.4"`). Python `>=3.13`. `scripts/test.sh` (Task 1) bootstraps a pinned uv 0.13.7 into /tmp when the system uv is older, and runs every suite; it is the one command CI and reviewers run.
- Every /api route requires either a Cloudflare Access identity header or a bearer token with scopes ingest/read/write, no anonymous mode.
- No secrets, customer data or message bodies stored. Event payloads carry changed fields only. Ingest rejects unknown fields (`extra="forbid"`).
- Nothing private to the owner's setup in the repo (thread ids, chat assistant, project names, private note paths, other people's names). Configuration comes from env or gitignored config files, each with an example file. Tests, fixtures and examples use the neutral human name `owner` (for example `human:owner`) and neutral project keys (`DEMO`).
- Tests: pytest for worker logic; D1 access only in `worker/src/loopboard/db.py`; the in-memory fake (`worker/tests/fakes/d1.py`) implements the same `prepare/bind/all/first/run/batch` surface. Vitest for web. GitHub Actions runs worker, connector and web tests.
- No deploy, no DNS, no push, no new remotes in any task. The repo already exists (public) with this plan and docs/design.md on `main`; those are rollout steps needing the owner's OK.
- Non-goals: v1b (chat sessions, Paperclip, driver, nudge, digest, `L-` codes) and v2 (invoking work). v1 connectors are read-only: abilities `["read"]`.

**Column rules (design, Workflow; exact):**
- Backlog: parked idea. Captured by an agent or the owner. No agent starts from here.
- Todo: the owner said go. Manual: the owner's "go" is the only drag on the board.
- In progress: automatic, any task running.
- Review: automatic, no task running and at least one in review, or code merged but not live.
- Done: automatic, all tasks done and deploy evidence present. Epics without code are confirmed by a human. Hidden after 7 days, never deleted.
- Canceled: hidden from the board.
- Stage label (idea, spec, plan, build, review, ship) set through the API. Agents never set the column. Blocked and stalled are flags, not columns. Waiting on is required on every open card.

**Source status mappings (design, Workflow; v1a connectors):**
- Hermes Kanban: triage, todo, ready → Todo; running → In progress; review → Review; done → Done; blocked → flag.
- GitHub PR: draft → In progress; open → Review; merged → Review with "merged, not live" until deployed; closed unmerged → ignored.

**Decisions where the design is silent (the reviewer confirms with the plan):**
- D1 Log and state: each write appends an event and updates the current row in the same `Repo.batch`. Events carry the new values of changed fields. A test rebuilds current state from events (design: "current state is a projection of the log").
- D2 Access: `Cf-Access-Authenticated-User-Email` counts only with a verified `Cf-Access-Jwt-Assertion` (RS256 against team certs, audience `ACCESS_AUD`). Access is off unless `ACCESS_TEAM_DOMAIN` and `ACCESS_AUD` are set. A bare header is rejected, since workers.dev accepts any header.
- D3 Deploy evidence = `live_at` on an item, set by `POST /api/items/{id}/deployed` or ingest. A merged PR stays Review until `live_at` is set.
- D4 `waiting_on` is `agent:<name>`, `human:<name>` or `source:<system>`. Required on open items (422 otherwise). Done and canceled items may send null.
- D5 Effective category: review + `merged_at` + `live_at` counts as done everywhere.
- D6 "Ignored" (design) = status category `canceled`, hidden and excluded from progress and stall. Kanban `archived` → canceled.
- D7 Epic derivation, first match wins:
  1. manual column `canceled` → `canceled` (hidden);
  2. any effective in_progress task → `in_progress`;
  3. any effective review task → `review`;
  4. at least one non-canceled task, all done: if the epic has code (an item with `merged_at`) or `done_confirmed_at` is set → `done`; else → `review` with flag `awaiting_confirmation`;
  5. no non-canceled tasks and `done_confirmed_at` set → `done`;
  6. otherwise the manual column (`backlog` or `todo`).
- D8 Review owner: `human` if any review task waits on a human or the epic is `awaiting_confirmation`; else `agent`. UI labels: "review · you", "review · agent".
- D9 Needs you = open epics or standalone items with `waiting_on` `human:*`, plus epics flagged `awaiting_approval`, `awaiting_confirmation` or `merged_not_live`. Oldest first by `last_activity_at`.
- D10 Stall. An item is stalled when its effective category is not done or canceled and `now - last_activity_at` exceeds its source threshold. An epic is stalled when its derived column is todo, in_progress or review and either it has open tasks whose newest `last_activity_at` is older than the shortest source threshold among them, or it has none and its own `last_activity_at` is older than 24 h. Backlog epics are never stalled. (The design's literal "no open tasks and not Done" would flag every empty epic at creation.)
- D11 Connectors are upsert-only. A listing never cancels, unfiles or deletes an item absent from it. A non-zero exit or unparseable output posts nothing.
- D12 Ingest is idempotent. A payload older than the stored `last_activity_at` is skipped with no event. An equal timestamp applies, so a replay changes nothing and writes no events.
- D13 Filing: new items are `unfiled` unless `epic_key` is given. Absent `epic_key` leaves filing unchanged. Standalone items show in Needs you and Stalled, not on the board. Unfiled items show only in Unfiled.
- D14 Relations (`blocks`) show on epic detail and do not change the derived column (design silent).
- D15 Epic keys `<PROJECT>-E<n>`, n a per-project sequence from 1.
- D16 Timestamps: ISO 8601 with an explicit offset or `Z`, stored as epoch seconds UTC. Naive timestamps are 422.
- D17 Tokens: `lb_` + 32 random bytes, base64url. Only the sha256 hex is stored. Created by `worker/scripts/make_token.py`, shown once. A token may be bound to one `source`; ingest for another source is 403.
- D18 Kanban: `owner` = `agent:<assignee>` or null; `next_step` always null (summaries can hold message text). `waiting_on`: triage → `human:<human>`; todo or ready → `agent:<assignee>` (`source:kanban` if unassigned); running → `agent:<assignee>`; review → `human:<human>`; blocked + `needs_input` → `human:<human>`; other blocked → `source:kanban`; done → null; archived → canceled, null.
- D19 GitHub: draft → `agent:<mapped author>` (unmapped → `human:<human>`). Open: failing checks → `agent:<author>`; pending checks → `source:CI`; else `human:<human>`. Merged → `human:<human>`. Closed unmerged → canceled, null.
- D20 Web: token in localStorage `loopboard.token`, sent as `Authorization: Bearer`. Phone widths show one column at a time with tabs. Moves use a Move menu on all sizes; drag is an extra on desktop. Offered moves: Backlog ↔ Todo, and Backlog/Todo → Canceled.
- D21 Screens follow the approved mockups (kept outside the repo); visual fidelity is reviewed by the owner after the build.
- D23 Live on merge (reviewer addition): a project may set `live_branches` per repo in connector config (e.g. `{"owner/app": ["main"]}`). A PR merged into a listed base branch gets `live_at = merged_at`; merged into any other branch it stays Review with `merged_not_live` until `POST /api/items/{id}/deployed`. Without it no v1a connector ever sets `live_at`, so every merged PR would sit in Review forever.
- D23a Live through a release (approved by the owner 2026-11-13, v1a.2; release check reworked in v1a.3): for the merged PRs whose base `B` is not in that repo's `live_branches`, which have a `merge_commit_sha` and whose `merged_at` is within `lookback_days`, the connector calls `GET /repos/{repo}/compare/{L}...{B}?per_page=250&page=N` once per (`B`, live branch `L`), paging until a page has fewer than 250 commits (more than `MAX_PAGES` is a `SourceError`). Those commits are what `B` has and `L` lacks: a PR is live in `L` iff its `merge_commit_sha` is not among them; without a `merge_commit_sha` it stays not live. Then `live_at` = the `merged_at` of the earliest PR in the same listing merged into `L` at or after this PR's `merged_at`, or the run time if none is found (the earliest across live branches wins). `merged_at` is unchanged. A 404 or 422 from compare means no PR into that `B` is live in `L`; any other error is a `SourceError` and the run posts nothing. This replaced the v1a.2 per-PR `compare/{merge_commit_sha}...{L}` with its 60-call budget, which re-checked the same oldest PRs every run because the connector is stateless. Fixes repos that merge features into `development` and release with `development → main`.
- D24 Kanban live shapes (verified on the host 2026-11-12): `list --json` task keys include `id, title, status, assignee, tenant, priority, created_at, started_at, completed_at, body, result, session_id`; there is **no `updated_at`**. Timestamps are **epoch seconds (int)**, not ISO. `show --json` → `{task, latest_summary, parents, children, comments, events, runs}`; events are `{kind, payload, created_at, run_id}`. The block kind is the `payload.kind` of the newest `kind == "blocked"` event (e.g. `needs_input`); `payload.reason` is free text and is never read. `body`, `result`, `latest_summary` and `comments` are never read.
- D22 `docs/design.md` is already the sanitized public design (committed before Task 1).

## Review Focus

The five input classes most likely to bite a real user, most likely first. Each has a test in its owning task.

1. Re-ingest of an item a human has filed or re-linked must keep that filing; the next sync must not unfile it. → Task 5, `test_reingest_keeps_filing_and_epic`.
2. A duplicate or out-of-order ingest must not roll back status, title or `last_activity_at`. → Task 5, `test_older_payload_does_not_regress_newer_state`, `test_replayed_batch_is_idempotent`.
3. A failing Kanban CLI, non-JSON output or a failing `show` must not cancel, unfile or delete existing items. → Task 10, `test_nonzero_exit_posts_nothing`, `test_unparseable_output_posts_nothing`, `test_one_show_failure_fails_whole_run`, `test_absent_items_are_untouched`.
4. Large listings (hundreds of Kanban cards) must not exceed Worker and D1 limits. Ingest caps a request at 100 items; the runner splits. → Task 5, `test_ingest_rejects_over_100_items`; Task 10, `test_runner_splits_250_items_into_three_posts`.
5. Timestamps with a local offset (`2026-11-12T09:00:00+07:00`, UTC+07:00) must be stored as the same instant as UTC; naive timestamps must not be read as UTC. → Task 4, `test_parse_ts_offset_to_utc`, `test_parse_ts_naive_rejected`; Task 5, `test_naive_timestamp_in_ingest_is_422`.

---

### Task 1: Project setup, sanitized design copy, CI

**Files:**
- Create: `.gitignore`, `README.md`, `.github/workflows/ci.yml`, `scripts/test.sh`
- Create: `worker/pyproject.toml`, `worker/wrangler.jsonc`, `worker/.dev.vars.example`, `worker/src/main.py`, `worker/src/loopboard/__init__.py`, `worker/tests/test_smoke.py`
- Create: `connectors/pyproject.toml`, `connectors/config.example.toml`, `connectors/src/loopboard_connectors/__init__.py`, `connectors/tests/test_smoke.py`
- Create: `web/` (Vite React TypeScript template), `web/src/smoke.test.ts`; modify `web/vite.config.ts`
- `scripts/test.sh` (Create) behaviour: `set -euo pipefail`; if `uv --version` < 0.13.4, `python3 -m pip install --quiet --target /tmp/lb-uv uv==0.13.7` and use `/tmp/lb-uv/bin/uv`; export `UV_CACHE_DIR=/tmp/lb-uv-cache UV_PYTHON_INSTALL_DIR=/tmp/lb-uv-py npm_config_cache=/tmp/lb-npm-cache`; run `uv run --python 3.13 pytest -q` in worker/ and connectors/, then `npm ci --no-audit --no-fund` and `npx vitest run` and `npm run build` in web/ (skip web until web/package-lock.json exists). CI calls `bash scripts/test.sh`.

**Interfaces:**
- Consumes: none.
- Produces: `loopboard.__version__ == "0.1.0"`; `loopboard_connectors.__version__ == "0.1.0"`. `worker/wrangler.jsonc`: `main: "src/main.py"`, `compatibility_date: "2026-11-12"`, `compatibility_flags: ["python_workers"]`, `d1_databases` binding `DB` (database_name `loopboard`, placeholder id `00000000-0000-0000-0000-000000000000`, replaced only at rollout), `assets` (`directory: "./public/"`, `binding: "ASSETS"`, `run_worker_first: ["/api/*"]`, `not_found_handling: "single-page-application"`), `vars` `ACCESS_TEAM_DOMAIN: ""`, `ACCESS_AUD: ""`, `triggers.crons: ["*/15 * * * *"]`, `migrations_dir: "migrations"`. `web/vite.config.ts`: `build.outDir: "../worker/public"`, `emptyOutDir: true`.

- [ ] **Step 1: Check the sanitized design is present:** `test -s docs/design.md`; run the generic private-path check `grep -rniE "/home/|~/" docs/design.md README.md worker/ connectors/ web/ scripts/` → no output (`docs/plans/` is excluded because it quotes this command).

- [ ] **Step 2: Set up the three packages.** Worker: runtime deps `fastapi`, `pydantic`; dev group `pytest`, `pytest-asyncio`, `httpx`, `cryptography`, `workers-py`, `workers-runtime-sdk`; `[tool.pytest.ini_options] asyncio_mode = "auto"`. Connectors: stdlib only at runtime; dev `pytest`; `[project.scripts] loopboard = "loopboard_connectors.cli:main"`. Web: Vite React TypeScript template plus `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`. `.gitignore`: `.venv/`, `node_modules/`, `worker/public/`, `.wrangler/`, `__pycache__/`, `dist/`, `.dev.vars`, `connectors/config.toml`, `connectors/config.local.toml`. CI: one job on Ubuntu with Node 22 and Python 3.13 that runs `bash scripts/test.sh` (it bootstraps uv and runs every suite).

- [ ] **Step 3: Verify the package layout under pywrangler.** `src/main.py`: `from loopboard import __version__`; `app = FastAPI()`; probe route `GET /probe` returns `{"version": __version__}`; `class Default(asgi.entrypoint(app)): pass`. Run `cd worker && uv run pywrangler dev --port 8799`; `curl -s localhost:8799/probe` → `{"version":"0.1.0"}`. If the package import fails, switch to flat modules and update every later Interfaces block before continuing. Stop the server. If the build sandbox cannot run workerd/pywrangler, write the probe or script anyway, skip running it, and list it under "Not verified offline" in the final report; the reviewer runs it on a host.

- [ ] **Step 4: Run the setup tests.** `cd worker && uv run pytest -q` → `1 passed`. `cd connectors && uv run pytest -q` → `1 passed`. `cd web && npm test -- --run` → `1 passed`. `npm run build` → `worker/public/index.html` exists.

- [ ] **Step 5: Run `bash scripts/test.sh` → all green.**

- [ ] **Step 6: Commit.** `git add -A && git commit -m "chore: set up worker, connectors, web, CI and sanitized design"`

---

### Task 2: Schema, migration and D1 repository

**Files:**
- Create: `worker/migrations/0001_init.sql`, `worker/src/loopboard/db.py`, `worker/tests/fakes/__init__.py`, `worker/tests/fakes/d1.py`, `worker/tests/conftest.py`, `worker/tests/test_db.py`

**Interfaces:**
- Produces:
  - `loopboard.db.Repo(db)`: `async first(sql, args=()) -> dict | None`; `async query(sql, args=()) -> list[dict]`; `async execute(sql, args=()) -> int` (last row id); `async batch(stmts: list[tuple[str, tuple]]) -> None` (one transaction; any failure rolls back all).
  - `tests/fakes/d1.py`: `FakeD1()` with `prepare(sql)` → query object with `bind(*args)`, `async all()`, `async first()`, `async run()`, `async batch(stmts)`. `all()` returns an object whose `.results.to_py()` is a list of dicts, matching Workers D1.
  - Fixture `repo` (conftest): `Repo(FakeD1())` with `0001_init.sql` applied.
  - Tables. `column` is reserved, so the epic column is `board_column`.
    - `projects(id pk, key unique not null, name not null, created_at int not null)`
    - `epics(id pk, project_id fk not null, seq int not null, key unique not null, title not null, goal, manual_column not null check in (backlog,todo,canceled), board_column not null, stage not null check in (idea,spec,plan,build,review,ship), owner, next_step, waiting_on, home_url, spec_url, plan_url, done_confirmed_at int, done_at int, last_activity_at int not null, stalled_since int, created_at int not null, updated_at int not null, unique(project_id, seq))`
    - `items(id pk, source not null, external_id not null, unique(source, external_id), project_id fk, epic_id fk, filing not null check in (unfiled,epic,standalone,ignored), title not null, url, status_category not null check in (backlog,todo,in_progress,blocked,review,done,canceled), raw_status, owner, waiting_on, blocked_reason, next_step, last_activity_at int not null, merged_at int, live_at int, stalled_since int, created_at int not null, updated_at int not null)`
    - `relations(id pk, kind not null check in (blocks), from_type check in (epic,item), from_id int, to_type check in (epic,item), to_id int, created_at int not null, unique(kind, from_type, from_id, to_type, to_id))`
    - `events(id pk, at int not null, actor not null, via not null, subject_type not null, subject_id int not null, kind not null, payload not null)`; triggers `events_no_update` and `events_no_delete` → `RAISE(ABORT, 'events are append-only')`.
    - `api_tokens(id pk, name unique not null, token_hash unique not null, scopes not null, source, created_at int not null, revoked_at int)`
    - `sources(name pk, stall_hours real not null default 24, updated_at int not null)`

- [ ] **Step 1: Write the failing tests** in `test_db.py`:
  - `test_migration_creates_tables`: `sqlite_master` names ⊇ `{projects, epics, items, relations, events, api_tokens, sources}`.
  - `test_events_are_append_only`: insert an event; `update events` and `delete from events` each raise with `match="append-only"`.
  - `test_batch_is_one_transaction`: two inserts into `projects` with the same key → raises; `query("select * from projects") == []`.
  - `test_first_returns_none_when_missing`.
  - `test_repo_reads_plain_list_results`: a stub whose `.results` is a plain list of dicts → `query` returns those dicts.

- [ ] **Step 2: Run to verify failure.** `cd worker && uv run pytest tests/test_db.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement** the migration, `FakeD1`, `conftest.py` and `Repo`. `Repo` reads rows as `res.results.to_py()` when present, else `list(res.results)`. `execute` returns `res.meta["last_row_id"]`; if D1's Python binding lacks `meta`, return `select last_insert_rowid()` from a follow-up query and note it in `db.py`.

- [ ] **Step 4: Run to verify pass.** `uv run pytest tests/test_db.py -q` → `5 passed`.

- [ ] **Step 5: Probe D1 on the real runtime.** Temporarily add `GET /probe/db` to `main.py`: runs `Repo.batch` (two inserts) and `Repo.execute`. Apply `npx wrangler d1 execute loopboard --local --file=migrations/0001_init.sql`; `uv run pywrangler dev --port 8799`; `curl localhost:8799/probe/db` → `{"batch":"ok","last_row_id":<int>}`. Remove both probes in Task 3. If the build sandbox cannot run workerd/pywrangler, write the probe or script anyway, skip running it, and list it under "Not verified offline" in the final report; the reviewer runs it on a host.

- [ ] **Step 6: Commit.** `git add -A && git commit -m "feat(worker): schema, migration and D1 repository"`

---

### Task 3: Authentication, scopes and route guard

**Files:**
- Create: `worker/src/loopboard/auth.py`, `worker/src/loopboard/app.py`, `worker/scripts/make_token.py`, `worker/tests/test_auth.py`, `worker/tests/test_api_guard.py`
- Modify: `worker/src/main.py` (remove the `/probe` and `/probe/db` probes; use `build_app()`)

**Interfaces:**
- Consumes: Task 2 `Repo`.
- Produces:
  - `auth.Principal`: dataclass `name: str`, `kind: Literal["token","access"]`, `scopes: frozenset[str]`, `source: str | None`.
  - `auth.AccessConfig(team_domain: str, aud: str)`; `auth.AuthError(Exception)`.
  - `auth.hash_token(token) -> str` (sha256 hex); `auth.new_token() -> tuple[str, str]` → `(token, hash)`.
  - `auth.verify_access_jwt(token, access, *, jwks: dict, now: int, verify_sig: Callable[[bytes, bytes, dict], bool]) -> dict`: three parts; `alg == "RS256"`; `kid` in jwks; `iss == f"https://{team_domain}"`; `aud` contains `aud`; `exp > now`; `verify_sig(signing_input, signature, jwk)`. Raises `AuthError`.
  - `auth.web_crypto_verify(signing_input, signature, jwk) -> bool` (production; imports `js` inside the function).
  - `auth.authenticate(request, repo, *, access, jwks, verify_sig, now) -> Principal`: `Authorization: Bearer` → token row by hash with `revoked_at is null` → kind token, scopes from csv, source from the row. Else, if `access` is set and `Cf-Access-Jwt-Assertion` is present → verify → kind access, name = email claim, scopes `{ingest, read, write}`, source None. Otherwise `AuthError`.
  - `auth.require(scope: str)`: FastAPI dependency; `AuthError` → 401; missing scope → 403.
  - `app.build_app(*, db=None, clock=None, access=None, jwks=None, verify_sig=None) -> FastAPI`: with `db`, sets `app.state.repo = Repo(db)`; sets `app.state.clock` (default `time.time`), `access`, `jwks` (default `{}`), `verify_sig`.
  - `app.get_repo(request)` (state, else `Repo(request.scope["env"].DB)`); `app.get_now(request) -> int`; `app.get_access(request)` (state, else `scope["env"]` `ACCESS_TEAM_DOMAIN`/`ACCESS_AUD`; both non-empty → config, else None).
  - `GET /api/health` (scope read) → `{"ok": true, "principal": name}`.
  - `make_token.py --name NAME --scopes ingest,read,write [--source SRC]`: prints `TOKEN=lb_...` once, then the `INSERT INTO api_tokens(...)` SQL with only the hash.

- [ ] **Step 1: Write the failing tests.**
  - `test_auth.py`:
    - `test_bearer_token_authenticates_with_its_scopes` (→ 200, principal name).
    - `test_unknown_bearer_is_401`; `test_revoked_token_is_401`.
    - `test_read_token_cannot_use_ingest_scope`: test-only route with `Depends(require("ingest"))` → 403.
    - `test_token_bound_to_source_is_recorded`: principal `source == "kanban"`.
    - `test_token_stored_only_as_hash`: stored `token_hash == hash_token(token)`; the token string appears in no column.
    - `test_forged_access_header_without_jwt_is_401`.
    - `test_valid_access_jwt_grants_all_scopes`: RS256 token signed in the test with `cryptography`; RSA verifier built on `cryptography` → 200, kind `access`, scopes `{ingest, read, write}`.
    - `test_access_jwt_wrong_audience_is_401`; `test_access_jwt_expired_is_401`; `test_access_disabled_ignores_valid_jwt`.
    - `test_make_token_prints_hash_not_token` (subprocess; printed SQL contains `hash_token(token)` and not `token`).
  - `test_api_guard.py`:
    - `test_every_api_route_requires_credentials`: for each `/api/` route and method, send no credentials and body `{}` (path params `1`) → 401. Covers later routes automatically.

- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/test_auth.py tests/test_api_guard.py -q` → FAIL.

- [ ] **Step 3: Implement** `auth.py`, `app.py`, `make_token.py`; wire `main.py` with `app = build_app()` and `class Default(asgi.entrypoint(app)): pass`.

- [ ] **Step 4: Run to verify pass.** Same command → pass.

- [ ] **Step 5: Commit.** `git add -A && git commit -m "feat(worker): bearer tokens, scopes, Access JWT and route guard"`

---

### Task 4: Derived state: column, flags, stall, recompute

**Files:**
- Create: `worker/src/loopboard/model.py`, `worker/src/loopboard/derive.py`, `worker/src/loopboard/stall.py`, `worker/src/loopboard/recompute.py`, `worker/tests/test_model.py`, `worker/tests/test_derive.py`, `worker/tests/test_stall.py`, `worker/tests/test_recompute.py`

**Interfaces:**
- Consumes: Task 2 `Repo`.
- Produces:
  - `model`: `CATEGORIES` (7), `OPEN_CATEGORIES = ("backlog","todo","in_progress","blocked","review")`, `FILINGS`, `EPIC_MANUAL_COLUMNS = ("backlog","todo","canceled")`, `STAGES`, `DAY = 86400`, `DONE_HIDE_SECONDS = 7 * DAY`, `REVIEW_WARN_AT = 3`, `STALL_DEFAULT_HOURS = 24.0`, `class ValidationError(ValueError)`, `parse_ts(value: str) -> int` (D16; naive or unparseable → `ValidationError`).
  - `derive.effective_category(item: dict) -> str` (D5).
  - `derive.Derived`: dataclass `board_column: str`, `flags: list[str]`, `review_owner: str | None`, `done: int`, `total: int`, `has_code: bool`, `hidden: bool`.
  - `derive.derive_epic(epic: dict, items: list[dict], now: int) -> Derived`. Epic keys: `manual_column`, `stage`, `waiting_on`, `done_confirmed_at`, `done_at`. Item keys: `status_category`, `filing`, `merged_at`, `live_at`, `waiting_on`, `blocked_reason`. Items with `filing == "ignored"` are excluded. Flags: `blocked`, `blocked_needs_input`, `awaiting_approval`, `merged_not_live`, `awaiting_confirmation`. `hidden`: `board_column == "canceled"`, or `done` with `done_at` set and `now - done_at > DONE_HIDE_SECONDS`.
  - `stall.threshold_hours(thresholds: dict[str, float], source: str) -> float` (default 24.0).
  - `stall.item_stalled(item, now, thresholds) -> bool` (item keys: `source`, `filing`, `status_category`, `merged_at`, `live_at`, `last_activity_at`).
  - `stall.epic_stalled(epic, items, derived: Derived, now, thresholds) -> bool` (D10).
  - `recompute.recompute_epic(repo, epic_id: int, *, actor: str, via: str, now: int) -> str`: loads the epic and its items, derives, updates `board_column`, `done_at` (set on entering done, cleared on leaving), `updated_at`. If the column changed, appends `epic.column_changed` with `{"from", "to"}`. Returns the new column.

- [ ] **Step 1: Write the failing tests.**
  - `test_model.py`: `test_parse_ts_offset_to_utc` (`parse_ts("2026-11-12T09:00:00+07:00") == parse_ts("2026-11-12T02:00:00Z")`); `test_parse_ts_naive_rejected`; `test_parse_ts_garbage_rejected`.
  - `test_derive.py`: parametrized table. `NOW = 1_800_000_000`. `it(cat, *, merged=None, live=None, waiting="agent:hermes", blocked=None, filing="epic")`; `ep(manual="todo", *, stage="build", waiting=None, confirmed=None, done_at=None)`. Cases `(name, epic, items, column, flags ⊇, owner)`:
    1. running → `in_progress`, `[]`, `None`
    2. `[in_progress, review]` → `in_progress`
    3. `[it("review")]` → `review`, `[]`, `agent`
    4. `[it("review", waiting="human:owner")]` → `review`, `[]`, `human`
    5. `[it("review", merged=1, waiting="human:owner")]` → `review`, `["merged_not_live"]`, `human`
    6. `[it("review", merged=1, live=2)]` → `done`, `[]`, `None`
    7. `[it("done", merged=1, live=2), it("done")]` → `done`
    8. `[it("done")]` → `review`, `["awaiting_confirmation"]`, `human`
    9. `ep(confirmed=5)`, `[it("done")]` → `done`
    10. `ep("todo")`, `[]` → `todo`
    11. `ep("backlog")`, `[]` → `backlog`
    12. `ep("canceled")`, `[]` → `canceled`, hidden True
    13. `[it("done", merged=1, live=2), it("canceled")]` → `done`
    14. `[it("blocked")]` → `todo`, `["blocked"]`
    15. `[it("blocked", blocked="needs_input")]` → `todo`, `["blocked", "blocked_needs_input"]`
    16. `ep("todo", stage="spec", waiting="human:owner")`, `[]` → `todo`, `["awaiting_approval"]`
    17. `[it("in_progress", filing="ignored")]` → `todo`, `[]`
  - Separate tests: `test_progress_counts_done_over_non_canceled` (`[done+merged+live, todo, canceled]` → done 1, total 2); `test_effective_category_needs_live_for_done` (review+merged → review; +live → done); `test_done_hidden_only_after_seven_days` (`done_at = NOW - 7*DAY` → hidden False; one second older → True).
  - `test_stall.py`:
    - `test_item_stalled_after_default_24h` (`NOW-24*3600` → False; one second older → True).
    - `test_source_threshold_overrides_default` (`{"github": 4}`; 5 h old github item → True; kanban item same age → False).
    - `test_done_and_canceled_never_stalled`; `test_backlog_epic_never_stalled`.
    - `test_epic_stalled_when_no_open_task_moved` (open item 30 h old → True).
    - `test_epic_not_stalled_when_an_open_task_moved_recently`.
    - `test_empty_todo_epic_uses_own_activity` (25 h → True; 1 h → False).
    - `test_epic_threshold_is_shortest_source` (github 4 h and kanban 24 h, both 5 h old → True).
  - `test_recompute.py` (rows inserted with SQL):
    - `test_recompute_writes_column_and_one_event` (running item → `in_progress`; one `epic.column_changed`).
    - `test_no_event_when_column_unchanged`.
    - `test_done_at_set_on_entering_done_and_cleared_on_leaving`.

- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/test_model.py tests/test_derive.py tests/test_stall.py tests/test_recompute.py -q` → FAIL.

- [ ] **Step 3: Implement** the four modules per D5–D7, D10, D16.

- [ ] **Step 4: Run to verify pass.** Same command → pass.

- [ ] **Step 5: Commit.** `git add -A && git commit -m "feat(worker): derived epic column, flags, stall and recompute"`

---

### Task 5: Ingest API and item upsert

**Files:**
- Create: `worker/src/loopboard/ingest.py`, `worker/src/loopboard/routes/__init__.py`, `worker/src/loopboard/routes/ingest.py`, `worker/tests/test_ingest.py`
- Modify: `worker/src/loopboard/model.py` (add `ItemIn`, `IngestIn`), `worker/src/loopboard/app.py` (include the router)

**Interfaces:**
- Consumes: Task 2 `Repo`; Task 3 `require`, `Principal`, `get_repo`, `get_now`; Task 4 `parse_ts`, `ValidationError`, `recompute_epic`.
- Produces:
  - `model.ItemIn` (pydantic, `extra="forbid"`): `external_id` (1–200); `title` (1–300); `url` (≤500, optional); `status_category: Literal[CATEGORIES]`; `raw_status` (≤100); `owner` (≤100); `waiting_on` (regex `^(agent|human|source):[A-Za-z0-9._-]{1,64}$`); `blocked_reason: Literal["needs_input","other"] | None`; `next_step` (≤200); `project_key` (regex `^[A-Z][A-Z0-9]{1,9}$`); `epic_key` (regex `^[A-Z][A-Z0-9]{1,9}-E[0-9]+$`); `last_activity_at: str`; `merged_at: str | None`; `live_at: str | None`. Validators: timestamps via `parse_ts`; `waiting_on` required for open categories (D4).
  - `model.IngestIn`: `source` (regex `^[a-z][a-z0-9_-]{1,31}$`); `items: list[ItemIn]` (`max_length=100`).
  - `ingest.ingest_items(repo, *, source, items: list[ItemIn], actor, via, now) -> dict` → `{"accepted", "created", "updated", "skipped_older"}`. Per item in order: skip if stored `last_activity_at` > payload; else upsert and append `item.created` or `item.updated` (changed fields only). `epic_key` present → `filing = epic`, `epic_id` looked up (unknown → `ValidationError`); absent → unchanged; new items without it → `unfiled`. `project_key`, if present, must exist. `merged_at` and `live_at` set only when non-null. Then `recompute_epic` for every touched epic (old and new).
  - `POST /api/ingest` (scope ingest): token `source` ≠ body `source` → 403; `ValidationError` → 422.

- [ ] **Step 1: Write the failing tests** in `test_ingest.py`. Helper `payload(**over)` builds a valid kanban item (`status_category="todo"`, `waiting_on="agent:hermes"`, `last_activity_at="2026-11-12T09:00:00+07:00"`).
  - `test_ingest_creates_unfiled_item_with_created_event`: 200, `created == 1`, `filing == "unfiled"`; event `item.created`, `actor` = token name, `via` = `ingest`.
  - `test_epic_key_files_item_to_epic`.
  - `test_reingest_keeps_filing_and_epic` (Review Focus 1): file via `epic_key`; a human sets `filing='standalone'` by SQL; re-ingest with a newer timestamp and no `epic_key` → `filing == "standalone"`, `epic_id` unchanged. A human moves `epic_id` to another epic by SQL; re-ingest without `epic_key` → `epic_id` still the human's choice.
  - `test_older_payload_does_not_regress_newer_state` (Review Focus 2): newer `done` at t2, then older `in_progress` at t1 → stored `done`, `last_activity_at == t2`, `skipped_older == 1`, no new event.
  - `test_replayed_batch_is_idempotent` (Review Focus 2): same batch twice → `created == 0`, `updated == 0`, event count unchanged.
  - `test_duplicate_in_batch_last_by_timestamp_wins`: `[a(t1,"todo"), a(t2,"in_progress")]` → `in_progress`.
  - `test_offset_timestamp_normalised_to_utc` (Review Focus 5): stored equals `parse_ts("2026-11-12T02:00:00Z")`.
  - `test_naive_timestamp_in_ingest_is_422` (Review Focus 5).
  - `test_ingest_rejects_over_100_items` (Review Focus 4): 101 → 422; 100 → 200.
  - `test_open_item_without_waiting_on_is_422`; `test_done_item_may_send_null_waiting_on`.
  - `test_waiting_on_needs_prefix_is_422` (`"owner"`).
  - `test_unknown_field_is_422` (`body` field).
  - `test_unknown_epic_key_is_422`.
  - `test_token_bound_to_other_source_is_403`; `test_read_scope_token_cannot_ingest` → 403.
  - `test_event_payload_has_changed_fields_only`: a second ingest changing only `title` → payload keys `{"title"}`.

- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/test_ingest.py -q` → FAIL.

- [ ] **Step 3: Implement** the models, `ingest_items`, the route, and router registration.

- [ ] **Step 4: Run to verify pass.** `uv run pytest tests/test_ingest.py tests/test_api_guard.py -q` → pass.

- [ ] **Step 5: Commit.** `git add -A && git commit -m "feat(worker): idempotent ingest API with filing preservation"`

---

### Task 6: Write API: projects, epics, filing, deploy, relations, sources

**Files:**
- Create: `worker/src/loopboard/writes.py`, `worker/src/loopboard/routes/writes.py`, `worker/tests/test_writes.py`
- Modify: `worker/src/loopboard/model.py` (request models), `worker/src/loopboard/app.py` (include router)

**Interfaces:**
- Consumes: Task 2 `Repo`; Task 3 `require("write")`, `Principal.name`; Task 4 `recompute_epic`.
- Produces:
  - Request models (`model.py`): `ProjectIn(key, name ≤100)`; `EpicIn(title 1–200, goal ≤2000, stage default "idea", owner ≤100, next_step ≤200, waiting_on, home_url, spec_url, plan_url, manual_column default "backlog")`; `EpicPatch` (all optional; `manual_column` in `EPIC_MANUAL_COLUMNS`; `stage` in STAGES); `FilingIn(filing: Literal["epic","standalone","ignored"], epic_key: str | None, project_key: str | None)`; `DeployedIn(live_at: str)`; `RelationIn(from_type, from_id, to_type, to_id)`; `SourceIn(stall_hours: float, gt=0, le=8760)`.
  - `writes.create_project(repo, *, key, name, actor, now)`; `writes.create_epic(repo, *, project_key, body: EpicIn, actor, now)` (assigns D15 key; recomputes); `writes.patch_epic(repo, *, key, changes: EpicPatch, actor, now)` (empty patch → 422; recomputes); `writes.confirm_done(repo, *, key, actor, now)`; `writes.set_filing(repo, *, item_id, body: FilingIn, actor, now)` (`epic` needs `epic_key`; `standalone` needs a project from `project_key` or the item; recomputes old and new epic); `writes.mark_deployed(repo, *, item_id, live_at: int, actor, now)` (item must have `merged_at`); `writes.create_relation(repo, *, body: RelationIn, actor, now)`; `writes.delete_relation(repo, *, relation_id, actor, now)`; `writes.put_source(repo, *, name, stall_hours, actor, now)`.
  - Routes (scope write): `POST /api/projects` (201; duplicate 409); `POST /api/projects/{project_key}/epics` (201; unknown project 404); `PATCH /api/epics/{key}` (200); `POST /api/epics/{key}/confirm-done` (200); `POST /api/items/{item_id}/filing` (200); `POST /api/items/{item_id}/deployed` (200); `POST /api/relations` (201; missing endpoint 404; self 422; duplicate 409); `DELETE /api/relations/{relation_id}` (204); `PUT /api/sources/{name}` (200).
  - Events: `project.created`, `epic.created`, `epic.updated`, `epic.confirmed_done`, `item.filed`, `item.deployed`, `relation.created`, `relation.deleted`, `source.updated`. Changed fields only. Each write sets `last_activity_at = now` on the epic it touches.

- [ ] **Step 1: Write the failing tests** in `test_writes.py`:
  - `test_create_epic_assigns_sequential_keys` (`DEMO-E1`, `DEMO-E2`); `test_create_epic_defaults_manual_backlog_stage_idea`.
  - `test_patch_epic_rejects_derived_column` (`manual_column="in_progress"` → 422); `test_patch_epic_empty_body_is_422`.
  - `test_patch_event_payload_has_changed_fields_only` (only `stage` → `{"stage"}`).
  - `test_every_write_records_actor_and_via` (`actor` = token name, `via` = `api`).
  - `test_patch_recomputes_board_column` (`backlog` → `todo`).
  - `test_confirm_done_moves_code_less_epic_to_done` (`review` → `done`).
  - `test_filing_moves_item_and_recomputes_both_epics`.
  - `test_filing_standalone_needs_project_else_422`; `test_filing_ignored_removes_item_from_derivation`.
  - `test_deployed_requires_merged_pr` (kanban item → 422); `test_deployed_moves_epic_to_done_when_all_done`.
  - `test_relation_requires_existing_endpoints` (404); `test_relation_self_is_422`; `test_relation_duplicate_is_409`.
  - `test_delete_relation_removes_row_and_logs_event`.
  - `test_put_source_rejects_zero_hours` (422).

- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/test_writes.py -q` → FAIL.

- [ ] **Step 3: Implement** `writes.py`, the models, and the router. Each write is one `Repo.batch` of the state change and its event (D1).

- [ ] **Step 4: Run to verify pass.** `uv run pytest tests/test_writes.py tests/test_api_guard.py -q` → pass.

- [ ] **Step 5: Commit.** `git add -A && git commit -m "feat(worker): write API for projects, epics, filing, deploy and sources"`

---

### Task 7: Read API and stall cron

**Files:**
- Create: `worker/src/loopboard/reads.py`, `worker/src/loopboard/routes/reads.py`, `worker/src/loopboard/cron.py`, `worker/tests/test_reads.py`, `worker/tests/test_cron.py`
- Modify: `worker/src/loopboard/app.py` (include router), `worker/src/main.py` (add `scheduled`)

**Interfaces:**
- Consumes: Task 2 `Repo`; Task 4 `derive`, `stall`, `model`; Task 3 `require("read")`, `get_repo`, `get_now`.
- Produces:
  - `reads.board(repo, *, now, project_key=None, waiting_on=None) -> dict`: `{"columns": [{"column", "label", "count", "warn", "cards"}]}` for backlog ("Backlog"), todo ("Todo"), in_progress ("In progress"), review ("Review"), done ("Done"). `warn` only for review with `count > REVIEW_WARN_AT`. Hidden: canceled, and done past `DONE_HIDE_SECONDS`. `waiting_on` ∈ {agent, human, source} matches the prefix.
  - Card: `{"id", "key", "title", "project_key", "column", "stage", "progress": {"done", "total"}, "owner", "waiting_on", "waiting_since", "stalled", "flags", "review_owner"}`. `waiting_since` = max of the epic's `last_activity_at` and its open tasks' `last_activity_at`.
  - `reads.needs_you(repo, *, now) -> list[dict]`: `{"kind": "epic"|"item", "id", "ref", "title", "waiting_on", "waiting_since", "reasons"}`, oldest first. Reason strings: "waiting on you", "awaiting your approval", "awaiting your confirmation", "merged, not live", "blocked: needs your input", "review · you".
  - `reads.stalled(repo, *, now, waiting_on=None) -> list[dict]`: `{"kind", "id", "ref", "title", "waiting_on", "waiting_group": "agent"|"human"|"source", "waiting_since", "stalled_for_hours"}`, oldest first.
  - `reads.unfiled(repo, *, now) -> list[dict]`: `{"id", "source", "external_id", "title", "url", "owner", "waiting_on", "last_activity_at"}`, oldest first.
  - `reads.epic_detail(repo, *, key, now) -> dict | None`: `{"epic": {card fields + "goal", "next_step", "home_url", "spec_url", "plan_url", "owner", "waiting_on", "flags", "review_owner", "board_column"}, "tasks": {"todo", "in_progress", "blocked", "review", "done"}, "relations", "events"}`. Tasks grouped by effective category, canceled excluded. Events newest first, at most 50.
  - `reads.projects(repo) -> list[dict]`.
  - `cron.run_stall_transitions(repo, *, now) -> dict` → `{"started": n, "cleared": m}`. Appends `stall.started` / `stall.cleared` (actor `cron`, via `cron`) and sets `stalled_since`.
  - Routes (scope read): `GET /api/projects`; `GET /api/board?project=&waiting_on=` (invalid `waiting_on` → 422); `GET /api/needs-you`; `GET /api/stalled?waiting_on=`; `GET /api/unfiled`; `GET /api/epics/{key}` (unknown → 404).
  - `main.py`: `async def scheduled(self, controller, env, ctx)` → `cron.run_stall_transitions(Repo(env.DB), now=int(time.time()))`.

- [ ] **Step 1: Write the failing tests.**
  - `test_reads.py`: `test_board_five_columns_in_order`; `test_board_card_has_contract_fields`; `test_board_warns_when_review_has_four_cards` (4 → true, 3 → false); `test_board_hides_done_after_seven_days` (7 days shown; 7 days + 1 s hidden); `test_board_excludes_canceled`; `test_board_filters_by_project_and_waiting_on`; `test_board_stalled_flag_matches_stall_rule`; `test_needs_you_oldest_first_with_reasons`; `test_needs_you_includes_standalone_item_waiting_on_human`; `test_stalled_grouped_by_waiting_group`; `test_stalled_filter_agent_only`; `test_unfiled_lists_only_unfiled_oldest_first`; `test_epic_detail_groups_tasks_into_five_groups`; `test_epic_detail_events_newest_first_limit_50`; `test_epic_detail_unknown_key_is_404`.
  - `test_cron.py`: `test_cron_records_stall_start_once` (two runs while stalled → started total 1); `test_cron_records_stall_clear`; `test_cron_ignores_done_items`.

- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/test_reads.py tests/test_cron.py -q` → FAIL.

- [ ] **Step 3: Implement** `reads.py`, `cron.py`, the router, and `scheduled` in `main.py`. Confirm the `*/15 * * * *` cron in `wrangler.jsonc`.

- [ ] **Step 4: Run to verify pass.** `uv run pytest -q` → whole worker suite passes.

- [ ] **Step 5: Verify the cron locally.** `uv run pywrangler dev --port 8799 --test-scheduled`; `curl "localhost:8799/cdn-cgi/handler/scheduled?cron=*/15+*+*+*+*"` → 200. Stop the server. If the build sandbox cannot run workerd/pywrangler, write the probe or script anyway, skip running it, and list it under "Not verified offline" in the final report; the reviewer runs it on a host.

- [ ] **Step 6: Commit.** `git add -A && git commit -m "feat(worker): read API and stall cron"`

---

### Task 8: Web shell and Board screen

**Files:**
- Create: `web/src/api.ts`, `web/src/token.ts`, `web/src/types.ts`, `web/src/App.tsx`, `web/src/index.css`, `web/src/components/TokenPrompt.tsx`, `web/src/components/Card.tsx`, `web/src/components/Column.tsx`, `web/src/screens/Board.tsx`, `web/src/api.test.ts`, `web/src/screens/Board.test.tsx`, `web/src/components/Card.test.tsx`
- Modify: `web/src/main.tsx`; delete the template demo files

**Interfaces:**
- Consumes: Task 7 `GET /api/board`; Task 6 `PATCH /api/epics/{key}`.
- Produces:
  - `api.ts`: `apiGet<T>(path)`, `apiPost<T>(path, body?)`, `apiPatch<T>(path, body)`, `apiPut<T>(path, body)`. Sends `Authorization: Bearer` when a token is stored. 401 → `AuthError`; other non-2xx → `ApiError` with `status`.
  - `token.ts`: `getToken()`, `setToken(t)`, `clearToken()` (localStorage key `loopboard.token`).
  - `types.ts`: `Card`, `ColumnData`, `BoardResponse`, `WaitingGroup = "agent"|"human"|"source"`.
  - `Card.tsx`: props `card`, `nowSeconds`, `onMove(column)`. Classes: `wait-human` (`human:`), `wait-agent` (`agent:`), `wait-source` (`source:`); `stalled` when `card.stalled`. Shows stage, `done/total`, project tag, flags as text ("awaiting your approval", "awaiting your confirmation", "blocked: needs your input", "blocked", "merged, not live"), and "waiting Nh".
  - `Column.tsx`: label and count; class `warn` and text "Review is backing up" when `warn`.
  - `Board.tsx` (`#/board`): filters for project (text) and waiting on (any, agent, human, source). Desktop: five columns. Narrow (`matchMedia("(max-width: 640px)")`): tabs, one column at a time. Move menu on Backlog and Todo cards per D20 → `apiPatch("/api/epics/<key>", {manual_column})`. Desktop drag from Backlog onto Todo calls the same PATCH; other drops do nothing. `AuthError` shows `TokenPrompt`; saving retries.

- [ ] **Step 1: Write the failing tests.**
  - `api.test.ts`: `test_bearer_header_sent_when_token_set`; `test_no_header_without_token`; `test_401_throws_AuthError`.
  - `Card.test.tsx`: `test_waiting_class_by_prefix`; `test_stalled_class`; `test_flags_text`; `test_progress_text_2_of_4`.
  - `Board.test.tsx` (stub `fetch` with `vi.stubGlobal`): `test_five_columns_in_order`; `test_review_warning_at_four_not_three`; `test_project_filter_requests_project_param`; `test_narrow_screen_shows_one_column_with_tabs`; `test_move_menu_offers_todo_not_in_progress_and_patches` (body `{manual_column: "todo"}`); `test_401_shows_token_prompt_and_retries_after_save`.

- [ ] **Step 2: Run to verify failure.** `cd web && npm test -- --run` → FAIL.

- [ ] **Step 3: Implement** the modules. CSS only to the extent the tests and basic layout need; visual fidelity is reviewed by the owner after the build (D21).

- [ ] **Step 4: Run to verify pass.** `npm test -- --run && npm run build` → pass; `worker/public/index.html` exists.

- [ ] **Step 5: Commit.** `git add -A && git commit -m "feat(web): shell, token prompt and five-column board"`

---

### Task 9: Web screens: Needs you, Stalled, Unfiled, Epic detail

**Files:**
- Create: `web/src/screens/NeedsYou.tsx`, `web/src/screens/Stalled.tsx`, `web/src/screens/Unfiled.tsx`, `web/src/screens/EpicDetail.tsx`, `web/src/components/TaskCard.tsx`, `web/src/components/ActivityLog.tsx`, `web/src/screens/Lists.test.tsx`, `web/src/screens/EpicDetail.test.tsx`
- Modify: `web/src/App.tsx` (hash routes `#/board`, `#/needs-you`, `#/stalled`, `#/unfiled`, `#/epic/<key>`; default `#/board`; four nav links)

**Interfaces:**
- Consumes: Task 7 read routes; Task 6 `POST /api/items/{id}/filing`, `POST /api/epics/{key}/confirm-done`; Task 8 `api.ts`, `types.ts`.
- Produces:
  - `NeedsYou.tsx`: `GET /api/needs-you` rows in server order with reasons. Epic rows link to `#/epic/<ref>`; item rows link to `url`.
  - `Stalled.tsx`: `GET /api/stalled` grouped under "Waiting on agent", "Waiting on you", "Waiting on source" by `waiting_group`.
  - `Unfiled.tsx`: `GET /api/unfiled`. Per row: "File to epic" (epic key input → `{filing: "epic", epic_key}`), "Standalone" (project key input → `{filing: "standalone", project_key}`), "Ignore" (→ `{filing: "ignored"}`). Success removes the row.
  - `EpicDetail.tsx`: `GET /api/epics/<key>`. Header: title, stage, next step, owner, waiting on, progress, flags. "Confirm done" button only when flags include `awaiting_confirmation`. Task groups in order Todo, In progress, Blocked, Review, Done. `TaskCard`: title, waiting on, link to `url` with `target="_blank" rel="noreferrer"`, no `draggable`. `ActivityLog`: newest first.

- [ ] **Step 1: Write the failing tests.**
  - `Lists.test.tsx`: `test_needs_you_renders_server_order_with_reasons`; `test_stalled_groups_by_waiting_group`; `test_unfiled_file_to_epic_posts_filing_body`; `test_unfiled_ignore_posts_ignored_and_removes_row`.
  - `EpicDetail.test.tsx`: `test_task_groups_in_order`; `test_task_link_opens_new_tab_and_is_not_draggable`; `test_confirm_done_only_when_awaiting_confirmation_and_posts`; `test_activity_newest_first`.

- [ ] **Step 2: Run to verify failure.** `npm test -- --run` → FAIL.

- [ ] **Step 3: Implement** the screens and hash routing.

- [ ] **Step 4: Run to verify pass.** `npm test -- --run && npm run build` → pass.

- [ ] **Step 5: Commit.** `git add -A && git commit -m "feat(web): needs-you, stalled, unfiled and epic detail screens"`

---

### Task 10: Kanban connector and `loopboard sync kanban`

**Files:**
- Create: `connectors/src/loopboard_connectors/contract.py`, `client.py`, `config.py`, `kanban.py`, `cli.py`, `connectors/tests/fixtures/kanban/list.json`, `connectors/tests/fixtures/kanban/show-<id>.json` (one per task), `connectors/tests/fixtures/kanban/expected-board.json`, `connectors/tests/test_kanban.py`, `connectors/tests/test_cli.py`, `docs/connectors.md`
- Modify: `connectors/config.example.toml`, `connectors/src/loopboard_connectors/__init__.py`

**Interfaces:**
- Consumes: the Task 5 `POST /api/ingest` contract.
- Produces:
  - `contract.ABILITIES = ("read",)`; `contract.SourceError(RuntimeError)`; `contract.ConfigError(RuntimeError)`; `contract.IngestRejected(RuntimeError)` with `status`.
  - `contract.Item`: dataclass `source, external_id, title, url, status_category, raw_status, owner, waiting_on, blocked_reason, next_step, project_key, epic_key, last_activity_at: str, merged_at: str | None, live_at: str | None`. `to_payload() -> dict` omits `epic_key` when None (so ingest keeps filing).
  - `config.load_config(path) -> dict` (tomllib); `config.resolve_token(cfg, env) -> str` (env var named by `loopboard.token_env`; missing → `ConfigError`).
  - `client.IngestClient(base_url, token, *, post=None)`: `send(source, items) -> dict` chunks by 100 and sums counts. `post(url, body: bytes, headers) -> dict` default urllib. HTTP error → `IngestRejected`.
  - `kanban.collect(run_cli: Callable[[list[str]], str], *, human, tenants: dict[str, str], board: str | None) -> list[Item]`: `hermes kanban [--board SLUG] list --json`, then `show <id> --json` per task. Any failure, bad JSON or missing field → `SourceError` for the whole run.
  - `kanban.map_task(task, show, *, human, tenants) -> Item` (D18). `source="kanban"`, `external_id=str(task["id"])`, `url=None`, `raw_status=task["status"]`, `project_key=tenants.get(task.get("tenant"))`, `last_activity_at` = max of `created_at`, `started_at`, `completed_at` and every `show["events"][*]["created_at"]` (epoch ints, D24), emitted as ISO with `Z`. `blocked_reason` = `payload.kind` of the newest `blocked` event (D24). `body`, `result`, `latest_summary`, comments and `payload.reason` are never read.
  - `kanban.run_cli_subprocess(argv) -> str` (non-zero → `SourceError`); `kanban.replay_runner(dir) -> Callable` reads `list.json` and `show-<id>.json`; missing file → `SourceError`.
  - `cli.main(argv, *, env=os.environ, post=None, run_cli=None) -> int`: `loopboard sync kanban --config PATH [--board SLUG] [--cli-replay DIR] [--dry-run]`. Prints one JSON summary line. Exit: 0 ok; 1 source failure (nothing posted); 2 config or token error; 3 ingest rejected. No output ever contains the token.

- [ ] **Step 1: Build fixtures from the verified shapes in D24 (do not call a live `hermes` CLI).** Synthetic fixtures: eight tasks, one per status case in D18, epoch-int timestamps, one blocked task whose newest `blocked` event has payload kind `needs_input`; put the marker `SECRET-BODY` in a comment, the task `body`, `result`, `latest_summary` and a blocked event `payload.reason`. Write `expected-board.json` (column counts expected from D7 and D18).

- [ ] **Step 2: Write the failing tests.**
  - `test_kanban.py`: one test row per D18 bullet, asserting `(status_category, waiting_on)` and `blocked_reason`; `test_tenant_maps_to_project_key` (unknown → None); `test_last_activity_uses_latest_event`; `test_free_text_never_in_payload` (fixture puts `SECRET-BODY` in a comment, the task `body`, `result`, `latest_summary` and a blocked event's `payload.reason`; `"SECRET-BODY" not in json.dumps(item.to_payload())`); `test_epoch_timestamps_emitted_as_utc_iso`; `test_block_kind_from_newest_blocked_event`; `test_one_show_failure_fails_whole_run` (Review Focus 3).
  - `test_cli.py`: `test_nonzero_exit_posts_nothing` (exit 1, `post` never called; Review Focus 3); `test_unparseable_output_posts_nothing` (exit 1); `test_absent_items_are_untouched` (second run with fewer tasks posts only current items, no `canceled` for absent ids); `test_empty_listing_posts_nothing_exits_0`; `test_runner_splits_250_items_into_three_posts` (100, 100, 50; Review Focus 4); `test_token_missing_exits_2`; `test_token_never_printed`; `test_dry_run_posts_nothing`; `test_ingest_422_exits_3`; `test_epic_key_omitted_from_payload_when_none`.

- [ ] **Step 3: Run to verify failure.** `cd connectors && uv run pytest -q` → FAIL.

- [ ] **Step 4: Implement** the modules; `config.example.toml` (`[loopboard] url`, `token_env`; `[general] human`; `[kanban] board`; `[kanban.tenants]` with generic keys); `docs/connectors.md` (contract, abilities, D18/D19 mapping, exit codes).

- [ ] **Step 5: Run to verify pass.** `uv run pytest -q` → pass.

- [ ] **Step 6: Commit.** `git add -A && git commit -m "feat(connectors): Hermes Kanban connector and sync CLI"`

---

### Task 11: GitHub PR connector

**Files:**
- Create: `connectors/src/loopboard_connectors/github.py`, `connectors/tests/fixtures/github/pulls.json`, `connectors/tests/fixtures/github/checks-<sha>.json`, `connectors/tests/fixtures/github/reviews-<n>.json`, `connectors/tests/test_github.py`
- Modify: `connectors/src/loopboard_connectors/cli.py` (dispatch `github`), `connectors/config.example.toml` (`[github]`), `docs/connectors.md` (GitHub section)

**Interfaces:**
- Consumes: Task 10 `contract.Item`, `client.IngestClient`, `cli.main`.
- Produces:
  - `github.collect(fetch_json: Callable[[str], Any], *, repos: dict[str, str], human, agent_logins: dict[str, str], live_branches: dict[str, list[str]], lookback_days: int, now: int) -> list[Item]` (`live_branches` per D23, from `[github.live_branches]` in config). `repos` maps `owner/name` → project key. Lists `https://api.github.com/repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=50`; for open non-draft PRs also fetches `/repos/{repo}/commits/{head_sha}/check-runs` and `/repos/{repo}/pulls/{number}/reviews`. Skips PRs with `updated_at` older than `now - lookback_days * 86400`. Fetch error → `SourceError`.
  - `github.map_pr(pr, *, checks, reviews, project_key, human, agent_logins, live_branches: list[str]) -> Item` (D19). `external_id = f"{repo}#{number}"`; `url = html_url`; `last_activity_at = updated_at`; `merged_at = merged_at`; `live_at = merged_at` only when `pr["base"]["ref"]` is in `live_branches` (D23), else None.
  - `github.default_fetch_json(token) -> Callable[[str], Any]`: urllib, `Authorization: Bearer`, `Accept: application/vnd.github+json`. Non-200 → `SourceError` with the status code only.
  - CLI: `loopboard sync github --config PATH [--dry-run]`; token from `[github] token_env`.

- [ ] **Step 1: Write the failing tests** in `test_github.py` (synthetic fixtures):
  - `test_draft_pr_is_in_progress_waiting_on_mapped_agent` → `(in_progress, agent:<name>)`.
  - `test_open_pr_with_failing_check_waits_on_author_agent` → `(review, agent:<name>)`.
  - `test_open_pr_with_pending_check_waits_on_ci` → `(review, source:CI)`.
  - `test_open_green_pr_waits_on_human` → `(review, human:owner)`.
  - `test_merged_pr_has_merged_at_and_no_live_at` → `(review, human:owner)`, `merged_at` set, `live_at` None (base branch not in `live_branches`).
  - `test_merge_into_live_branch_sets_live_at` (D23: base `main` listed → `live_at == merged_at`, effective category done).
  - `test_closed_unmerged_is_canceled` → `(canceled, None)`.
  - `test_unmapped_author_waits_on_human`.
  - `test_lookback_skips_old_prs`.
  - `test_fetch_failure_raises_source_error`; `test_cli_github_fetch_failure_exits_1_posts_nothing`.
  - `test_token_never_in_output`.

- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/test_github.py -q` → FAIL.

- [ ] **Step 3: Implement** `github.py`, the CLI dispatch, the config section and the docs section.

- [ ] **Step 4: Run to verify pass.** `uv run pytest -q` → pass.

- [ ] **Step 5: Commit.** `git add -A && git commit -m "feat(connectors): GitHub PR connector"`

---

### Task 12: Acceptance: local stack, HTTP check and docs

**Files:**
- Create: `scripts/acceptance-local.sh`, `docs/install.md`, `docs/api.md`, `worker/tests/test_api_doc.py`
- Modify: `README.md` (links to docs)

**Interfaces:**
- Consumes: every earlier task.
- Produces: `scripts/acceptance-local.sh` (exits 0 only when every check passes). `docs/api.md` lists every `/api` route as `METHOD /path`.

- [ ] **Step 1: Write the failing doc test.** `test_api_doc_lists_every_route`: every `/api` route in `build_app().routes` appears as `METHOD /path` in `docs/api.md`. Run → FAIL.

- [ ] **Step 2: Write `docs/api.md`** (auth, scopes, each route's body and status codes) and `docs/install.md` (local dev; `make_token.py`; Access setup; connector config; rollout steps marked "rollout, not part of the v1a build": first deploy, DNS, Access application, Hermes crons, Hermes skill changes). Run the doc test → PASS.

- [ ] **Step 3: Run the full suites.** `cd worker && uv run pytest -q`; `cd connectors && uv run pytest -q`; `cd web && npm test -- --run && npm run build`. All green.

- [ ] **Step 4: Write and run `scripts/acceptance-local.sh`.** It:
  1. runs `npx wrangler d1 migrations apply loopboard --local` in `worker/`;
  2. creates a `read,write` token and an `ingest` token bound to source `kanban` with `make_token.py`, inserts them via `wrangler d1 execute loopboard --local --command`, and exports them for this run only (nothing written to the repo);
  3. starts `uv run pywrangler dev --port 8799 --test-scheduled` in the background and waits for `GET /api/health` with the read token → 200;
  4. `POST /api/projects` with key `DEMO` → 201;
  5. `uv run loopboard sync kanban --config connectors/config.local.toml --cli-replay connectors/tests/fixtures/kanban` → exit 0, summary `collected: 8`, `accepted: 8`;
  6. `curl -s -H "Authorization: Bearer $READ" localhost:8799/api/board` → column counts equal `expected-board.json`; `curl -s -o /dev/null -w '%{http_code}' localhost:8799/api/board` → `401`;
  7. `curl -s "localhost:8799/cdn-cgi/handler/scheduled?cron=*/15+*+*+*+*"` → 200;
  8. records `curl -w '%{time_total}'` for a warm `/api/board` (informational; cold start and D1 free-tier usage remain unmeasured);
  9. stops the dev server and prints `ACCEPTANCE PASS` only if steps 3–7 passed.
  If a check fails, fix the owning task, not the script. If the build sandbox cannot run workerd/pywrangler, write the probe or script anyway, skip running it, and list it under "Not verified offline" in the final report; the reviewer runs it on a host.

- [ ] **Step 5: Re-run the private-path check** from Task 1 Step 1. Expected: no output.

- [ ] **Step 6: Commit.** `git add -A && git commit -m "docs, acceptance: local stack check for v1a"`. No deploy, no push.

---

## Scope notes

- Not built in v1a (by design): chat-session connector and classifier, Paperclip connector, driver, nudge and digest with `L-` codes (v1b); invoking work from epics (v2).
- Rollout steps, not built: first Cloudflare deploy, DNS record and Access application, Hermes crons (sync, classifier, driver, digest), Hermes skill changes that let agents create and update epics. Each needs the owner's OK.
- The "within an hour" success metric depends on the Hermes sync cron (rollout); v1a makes the connector runnable only.
