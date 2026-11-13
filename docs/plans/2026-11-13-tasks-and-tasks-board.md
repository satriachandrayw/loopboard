# Tasks and Tasks Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Jira-style Tasks between epics and items (storage, status rules, API, ingest linking, migration of existing data) and the screens that show them (Tasks board, task detail, epic detail task list, New task form, Unfiled linking).

**Architecture:** One expand-only migration adds `tasks` and `items.task_id`, backfills one task per filed item, and rebuilds `relations` to accept task endpoints. Task status is derived on read by a pure `derive_task`; `derive_epic` now runs over derived tasks. Ingest resolves `[KEY-n]` prefixes, refs and `[KEY-En]` auto-tasks in the same bounded batch. The web adds a `#/tasks` route behind an Epics | Tasks switch, plus `#/task/<KEY>`.

**Tech Stack:** Python 3.13 FastAPI on Cloudflare Workers + D1 (pydantic), pytest with the in-memory D1 fake; React + TypeScript, Vitest + Testing Library.

**Spec:** `docs/design-tasks.md` (read it first). Visual spec: the approved mockups the operator copies into `.ref/` (`tasks.html` sections `#s2` Tasks board, `#s3` epic and task detail, `#s4` New task form; PNGs alongside). `.ref/` is never committed.

## Global Constraints

- Migration `worker/migrations/0002_tasks.sql` is **expand-only** for `epics`, `items`, `projects`, `events`, `api_tokens`, `sources`: add, never drop or rename. `relations` may be rebuilt (create new, copy, drop old, rename) because it only gains allowed values.
- Keys: task `^[A-Z][A-Z0-9]{1,9}-[0-9]+$`, epic `^[A-Z][A-Z0-9]{1,9}-E[0-9]+$`. Task `seq` is per project, starts at 1, independent of epic `seq`.
- Field limits (spec table): summary 1-300; description non-blank max 2000; done_when non-blank max 300; owner non-blank max 100; refs max 10, each a task-key-shaped string, stored as a JSON array text; type `task|bug` default `task`; priority `high|medium|low` default `medium`; status `todo|in_progress|review|done|canceled` default `todo`. Strings are stripped; blank after strip → 422.
- `waiting_on` is required on create and whenever the manual status is not `done`/`canceled` (same pattern as epics).
- Invariant after this change: every item with `filing in ('epic','standalone')` has a `task_id`. Every code path that files an item (ingest, `POST /api/items/{id}/filing`, link endpoints, migration) keeps it. Linked items keep `filing='epic'` when the task has an epic, `'standalone'` when it has none, and `epic_id` = the task's epic.
- Human principal: `kind == "access"` or `"human" in scopes`. `make_token.py` accepts `human` alongside `read,write` (never with `ingest`).
- Every write appends events with actor and via, as today. New event kinds: `task.created`, `task.updated`, `task.status_changed`, `task.done_confirmed`, `task.merged`, `item.linked`, `item.unlinked`.
- D1 bounds: ingest stays within its current pattern (selects with `in (...)` of at most 99 ids, one write batch, retry once on a UNIQUE race, now including `tasks.project_id, tasks.seq`). No per-item queries.
- Repo rules from the v1a plan still hold: public repo, synthetic data (`DEMO`, `owner`), `bash scripts/test.sh` is the gate, `bash scripts/acceptance-local.sh` must print `ACCEPTANCE PASS`, `docs/api.md` documents every route (`test_api_doc_lists_every_route`). No deploy, push or remote database.
- Status reason copy (task detail and API `reason`), exactly:
  - canceled: `Canceled`
  - merged away: `Merged into <KEY>`
  - manual: `Moved by hand`
  - awaiting confirmation: `Done by an agent; waiting for a human to confirm`
  - in progress: `In progress: a linked item is running`
  - review, merged not live: `Review: a linked PR is merged but not live yet`
  - review: `Review: a linked item is in review`
  - done: `Done: every linked item is done`
  - blocked: `In progress: a linked item is blocked`
  - todo: `Todo: linked items haven't started`

## Review Focus

- An item tagged `[DEMO-E1]` that was **already filed** by a human to another epic stays where it is; no auto-task is created (`test_tag_never_overrides_existing_filing` extended to task keys and refs).
- Ref `OPS-80` must not link a title containing `OPS-8001`, and a ref of another project's task never links (`test_ref_matches_whole_token_in_same_project_only`).
- A task with live links rejects a manual move to anything but `canceled` with 422 `status follows its links` (`test_linked_task_status_is_not_manual`).
- An agent token moving a no-link task to `done` leaves it in Review with `awaiting_confirmation`; a human's confirm (or a human's own move) makes it Done; an agent calling confirm-done gets 403 (`test_agent_done_needs_human_confirmation`).
- Migration on a database with filed, standalone, unfiled and ignored items creates tasks only for filed and standalone ones, keeps every epic's derived column and its done/total unchanged, and gives each project consecutive keys (`test_0002_backfill_keeps_board_unchanged`).

---

### Task 1: Migration and backfill

**Files:**
- Create: `worker/migrations/0002_tasks.sql`
- Modify: `worker/tests/fakes/d1.py` (`apply_migrations(self, upto: str | None = None)` applies files whose name sorts `<= upto`)
- Test: `worker/tests/test_migration_0002.py`

**Interfaces:**
- Produces: table `tasks(id, project_id, epic_id, seq, key, type, summary, description, done_when, status, priority, owner, waiting_on, reporter, refs, merged_into, origin_item_id, done_confirmed_at, last_activity_at, stalled_since, created_at, updated_at)`, unique `(project_id, seq)` and `key`, checks on `type/status/priority`; `items.task_id integer references tasks(id)`; indexes `items(task_id)`, `tasks(epic_id)`, `tasks(project_id)`; `relations` check now allows `'task'` in `from_type`/`to_type`.

- [ ] **Step 1: Write the failing test.** Apply `0001`, insert 2 projects, epics (one canceled), items with filing epic/standalone/unfiled/ignored and categories todo/review-merged-not-live/done, capture `GET /api/board` columns and progress through `reads.board`; apply `0002`; assert: tasks exist exactly for epic/standalone items (`origin_item_id` set, `reporter='migration'`, `description` starts `Migrated from `, `done_when == 'The linked work is live.'`, status `todo`), keys per project are `DEMO-1..n` in item id order, every such item has `task_id`, a `task.created` event per task with actor `migration`, and the board (after Task 3's reads) is unchanged. Until Task 3 lands, assert the board part only after Task 3 (mark it `xfail(strict=True)` here and remove the marker in Task 3).
- [ ] **Step 2: Run** `cd worker && uv run --python 3.13 pytest -q tests/test_migration_0002.py` → FAIL (no migration).
- [ ] **Step 3: Implement** the SQL. Backfill with `row_number() over (partition by project_id order by items.id)` for `seq`; project = the epic's project for epic-filed items, `items.project_id` for standalone; owner `coalesce(nullif(trim(owner),''), source)`; timestamps from the item. Then `update items set task_id = (select id from tasks where origin_item_id = items.id) where filing in ('epic','standalone')`. Rebuild `relations` (it has 0 rows in practice, but copy anyway).
- [ ] **Step 4: Run** the test file and `bash scripts/test.sh` → PASS (existing suites unaffected).
- [ ] **Step 5: Commit** `feat(worker): tasks table, items.task_id and backfill migration`

### Task 2: Models and pure derivation

**Files:**
- Modify: `worker/src/loopboard/model.py` (constants `TASK_TYPES`, `TASK_STATUSES`, `PRIORITIES`, `TASK_KEY`, models `TaskIn`, `TaskPatch`, `TaskStatusIn`, `LinkIn`, `MergeIn`; `ItemIn.task_key`)
- Modify: `worker/src/loopboard/derive.py` (`derive_task`, `derive_epic` over tasks)
- Modify: `worker/src/loopboard/stall.py` (`task_stalled`)
- Test: `worker/tests/test_model.py`, `worker/tests/test_derive.py`, `worker/tests/test_stall.py`

**Interfaces:**
- Produces:
  - `TaskIn(summary, description, done_when, owner, waiting_on, type="task", priority="medium", epic_key=None, refs=[], item_id: int | None = None)`; `TaskPatch` = same fields all optional plus `epic_key` nullable (null = No epic); `TaskStatusIn(status)`; `LinkIn(task_key)`; `MergeIn(into)`.
  - `@dataclass TaskDerived(status: str, flags: list[str], reason: str, linked: bool, links_done: int, links_total: int)`.
  - `derive_task(task: dict, items: list[dict], merged_into_key: str | None = None) -> TaskDerived` (items = rows with `task_id == task["id"]`).
  - `derive_epic(epic: dict, tasks: list[TaskDerived], now: int) -> Derived` (same `Derived` fields; `done/total` count tasks excluding canceled; `has_code` dropped from the epic rule).
  - `task_stalled(task: dict, items: list[dict], derived: TaskDerived, now: int, thresholds: dict) -> bool`.

- [ ] **Step 1: Write failing tests** for every lifecycle line of the spec, one test each, e.g. `test_task_review_when_link_merged_not_live` (`status == "review"`, `"merged_not_live" in flags`, reason exact), `test_task_done_when_kanban_card_done`, `test_task_blocked_only_is_in_progress_with_flag`, `test_task_all_links_canceled_falls_back_to_manual`, `test_task_manual_done_unconfirmed_is_review_awaiting_confirmation`, `test_canceled_wins_over_links`, `test_epic_column_from_tasks` (one review task + one done → review, progress 1/2), `test_epic_done_when_all_tasks_done_without_code`, `test_epic_no_tasks_confirmed_is_done`, `test_task_stalled_uses_min_link_threshold_and_default_without_links`, model tests for blanks, limits, refs pattern and `waiting_on` requirement.
- [ ] **Step 2: Run** those files → FAIL.
- [ ] **Step 3: Implement.** Keep `effective_category`; existing epic tests that fed items to `derive_epic` are rewritten to feed `derive_task` results (one task per item reproduces the old expectations).
- [ ] **Step 4: Run** `bash scripts/test.sh` → PASS. The `derive_epic` signature change breaks its callers; update the call sites in `reads.py`, `recompute.py` and `cron.py` minimally (one task per filed item) so the suite is green at this commit. Task 3 does the real rewrite.
- [ ] **Step 5: Commit** `feat(worker): task models and derived task and epic status`

### Task 3: Reads over tasks

**Files:**
- Modify: `worker/src/loopboard/reads.py`, `worker/src/loopboard/recompute.py`, `worker/src/loopboard/cron.py`
- Test: `worker/tests/test_reads.py`, `worker/tests/test_recompute.py`, `worker/tests/test_cron.py`, `worker/tests/test_migration_0002.py` (drop the xfail)

**Interfaces:**
- Consumes: Task 2.
- Produces:
  - `load_tasks(repo, *, project_id=None, epic_ids=None) -> list[dict]` each `{"task": row, "items": [...], "derived": TaskDerived}`, two queries (tasks, items `where task_id in (...)` chunked).
  - `task_view(task, items, derived, *, project_key, epic_key, now, th) -> dict` with keys `id, key, type, summary, description, done_when, project_key, epic_key, status, flags, reason, priority, owner, waiting_on, waiting_since, stalled, refs (list), reporter, links_summary {"kanban": {"count", "state"}, "github": {...}} (only sources present), last_activity_at`.
  - `tasks_board(repo, *, project_key, now) -> {"project": key, "columns": ["todo","in_progress","review","done"], "lanes": [{"epic": {"key","title","progress"} | None, "tasks": {col: [task_view...]}}]}`; done tasks with `last_activity_at` older than 7 days are left out; canceled tasks are left out.
  - `task_detail(repo, *, key, now) -> dict | None`: `task_view` + `links` (item rows as today's epic-detail task entries) + newest 50 events for the task and its items.
  - `epic_detail` `tasks` becomes `[task_view...]` ordered by key seq; relations/events include task subjects.
  - `board`/`needs_you`/`stalled` use tasks: Needs you rows `kind: "task"` (reasons as today, plus `awaiting your confirmation`), replacing standalone item rows; Stalled `kind: "task"` rows replacing item rows. `recompute_epics` derives from tasks. Cron records `stall.started/cleared` for tasks (`tasks.stalled_since`) instead of items.

- [ ] **Step 1: Failing tests:** `test_board_progress_counts_tasks_not_items` (a task with a done Kanban card and a merged-not-live PR counts once: progress `0/1`, flag merged_not_live), `test_tasks_board_lanes_in_epic_order_then_no_epic`, `test_tasks_board_hides_old_done_and_canceled`, `test_task_detail_reason_and_links`, `test_needs_you_lists_tasks_waiting_on_human`, `test_stalled_lists_unstarted_planned_task_after_24h`, `test_cron_stall_transitions_for_tasks`, and the migration board-unchanged assertion.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4:** `bash scripts/test.sh` → PASS.
- [ ] **Step 5: Commit** `feat(worker): board, needs-you, stalled and epic detail read tasks; tasks board and task detail`

### Task 4: Task writes and routes

**Files:**
- Modify: `worker/src/loopboard/writes.py`, `worker/src/loopboard/routes/writes.py`, `worker/src/loopboard/routes/reads.py`, `worker/src/loopboard/auth.py` (`Principal.is_human`), `worker/scripts/make_token.py`, `docs/api.md`
- Test: `worker/tests/test_task_writes.py`, `worker/tests/test_writes.py`, `worker/tests/test_auth.py`, `worker/tests/test_api_doc.py` (unchanged, must pass)

**Interfaces:**
- Produces routes (all JSON; write routes need scope `write`, reads `read`):
  - `POST /api/projects/{project_key}/tasks` (TaskIn) → 201 `task_view`. `epic_key` must belong to the project (422 otherwise; 404 unknown). With `item_id`: links that item in the same batch.
  - `GET /api/projects/{project_key}/tasks` → `tasks_board`. `GET /api/tasks/{key}` → `task_detail` (404 unknown).
  - `PATCH /api/tasks/{key}` (TaskPatch) → `task_view`; moving `epic_key` re-points linked items' `epic_id`/`filing`.
  - `POST /api/tasks/{key}/status` (TaskStatusIn) → `task_view`; 422 `status follows its links` when the task has live links and status ≠ `canceled`; a human moving to `done` sets `done_confirmed_at`, an agent clears it.
  - `POST /api/tasks/{key}/confirm-done` (JSON content type required, like epic confirm-done) → `task_view`; 403 for non-human principals.
  - `POST /api/tasks/{key}/merge` (MergeIn) → survivor `task_view`; same project only (422), not into itself, not from/into a canceled task.
  - `POST /api/items/{item_id}/link` (LinkIn) → item row; `POST /api/items/{item_id}/unlink` → item row (`filing='unfiled'`, `task_id`/`epic_id` null).
  - Existing `POST /api/items/{id}/filing`: `epic` → creates an auto-task under that epic (Global Constraints) unless the item already has a task, then moves that task to the epic; `standalone` → auto-task with no epic; `ignored` → unlink.
  - `create_task(repo, *, project_key, body: TaskIn, actor, now) -> dict`, `patch_task`, `set_task_status(..., human: bool)`, `confirm_task_done`, `merge_tasks`, `link_item`, `unlink_item`, `auto_task_stmts(item: dict, *, project_id, epic_id, seq, key, actor, now) -> list` (shared with ingest).
  - Relations accept `from_type/to_type = "task"`.
- Every task write bumps the task's and its epic's `last_activity_at` and recomputes the affected epics.

- [ ] **Step 1: Failing tests:** `test_create_task_keys_per_project` (`DEMO-1`, `DEMO-2`; epic `DEMO-E1` unaffected), `test_create_task_validation` (blank description/done_when/owner, epic of another project), `test_create_task_with_item_links_it`, `test_linked_task_status_is_not_manual`, `test_agent_done_needs_human_confirmation`, `test_merge_moves_links_and_aliases_key`, `test_link_and_unlink_keep_invariant`, `test_filing_epic_creates_auto_task`, `test_patch_task_epic_moves_links`, `test_human_scope_token_is_human`, `test_make_token_accepts_human_scope_not_with_ingest`, `test_task_seq_race_is_409_not_500`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**, documenting every route in `docs/api.md`. **Step 4:** `bash scripts/test.sh` → PASS.
- [ ] **Step 5: Commit** `feat(worker): task write API, item linking and human principals`

### Task 5: Ingest and connectors

**Files:**
- Modify: `worker/src/loopboard/ingest.py`, `connectors/src/loopboard_connectors/contract.py` (`KEY_PREFIX` accepting `[KEY-n]` and `[KEY-En]`; `split_key_prefix(title) -> tuple[str | None, str | None, str]` returning `(epic_key, task_key, title)`), `kanban.py`, `github.py` (fill `task_key`), `docs/connectors.md`, `docs/api.md`
- Test: `worker/tests/test_ingest.py`, `connectors/tests/` (existing prefix tests extended)

**Interfaces:**
- Consumes: Task 4 `auto_task_stmts`.
- Produces: ingest response gains `linked_task`, `auto_tasks`, `unknown_task` counters (default 0) next to `unknown_epic`; the connector CLI summary line prints them.

- [ ] **Step 1: Failing tests:** `test_task_prefix_links_new_item`, `test_task_prefix_of_merged_task_links_survivor`, `test_ref_matches_whole_token_in_same_project_only`, `test_epic_prefix_creates_auto_task_and_links`, `test_two_items_same_epic_tag_get_two_tasks_in_one_batch` (consecutive keys), `test_tag_never_overrides_existing_filing` (epic, standalone, ignored; task key and ref too), `test_unknown_task_key_does_not_fail_chunk`, `test_ingest_d1_calls_bounded` (count repo calls for 100 items stays ≤ the current count + 3), connector `test_split_key_prefix_task_and_epic`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** in the existing single-batch shape: load tasks by key, refs of open tasks for the batch's projects, and `max(seq)` per project once; allocate seqs in memory; insert auto-tasks before the item statements and reference them by `(select id from tasks where key = ?)`. **Step 4:** `bash scripts/test.sh` → PASS.
- [ ] **Step 5: Commit** `feat: link ingested items to tasks by key, ref or epic tag`

### Task 6: Web data layer and Tasks board

**Files:**
- Modify: `web/src/types.ts` (`TaskView`, `TasksBoardResponse`, `TaskDetailResponse`; `EpicDetailResponse.tasks: TaskView[]`; `NeedsYouRow`/`StalledRow` kind `'task'`), `web/src/App.tsx` (routes `#/tasks`, `#/task/<KEY>`; `#/tasks` highlights Board in the nav), `web/src/format.ts` (`taskHref`)
- Create: `web/src/components/ViewSwitch.tsx` (Epics | Tasks), `web/src/components/TaskCard.tsx`, `web/src/screens/TasksBoard.tsx`
- Modify: `web/src/screens/Board.tsx` (renders `ViewSwitch`), `web/src/index.css`
- Test: `web/src/components/TaskCard.test.tsx`, `web/src/screens/TasksBoard.test.tsx`

**Interfaces:**
- Consumes: `GET /api/projects/{key}/tasks`, `POST /api/tasks/{key}/status`.
- Produces: `TaskCard({ task, nowSeconds, draggable })`, `TasksBoard()`.

Visual rules from mockup `#s2`: column header row once at the top; lane header = fold arrow, epic key (mono), title, a 90 px progress bar and `done/total`; "No epic" lane last with muted title; task card = key + type pill (`task` green-tinted, `bug` red-tinted) on the top line, summary, links summary line (`🗂 1 card done · ⑂ 1 PR merged`, or `no links yet`), waiting line (orange you / teal agent, red age when stalled), flags as on epic cards. No project chosen → the panel "Pick a project to see its tasks" above the project chips. Phone (≤ 640 px): column tabs with counts, lanes as small headings. Lane fold state persists in `localStorage` key `loopboard.lanes.<PROJECT>`.

- [ ] **Step 1: Failing tests:** `test_tasks_board_needs_a_project`, `test_lanes_render_in_api_order_with_no_epic_last`, `test_lane_folds_and_remembers`, `test_only_unlinked_cards_are_draggable`, `test_drop_posts_status_and_reloads`, `test_task_card_links_summary_and_flags`, `test_view_switch_routes_between_board_and_tasks`.
- [ ] **Step 2: Run** `cd web && npx vitest run` → FAIL. **Step 3: Implement.** **Step 4:** `bash scripts/test.sh` → PASS.
- [ ] **Step 5: Commit** `feat(web): Tasks board with epic swimlanes and an Epics | Tasks switch`

### Task 7: Task detail, epic detail tasks, New task form, Unfiled, lists

**Files:**
- Create: `web/src/screens/TaskDetail.tsx`, `web/src/components/NewTaskForm.tsx`
- Modify: `web/src/screens/EpicDetail.tsx` (task list + `+ Add task`), `web/src/screens/Unfiled.tsx` (`Link to task ▾`, `New task from this…`, `Ignore`), `web/src/screens/NeedsYou.tsx`, `web/src/screens/Stalled.tsx` (task rows link to `#/task/<KEY>`), `web/src/screens/TasksBoard.tsx` (`+ Task` button)
- Test: `web/src/screens/TaskDetail.test.tsx`, `web/src/components/NewTaskForm.test.tsx`, updated `EpicDetail.test.tsx`, `Unfiled.test.tsx`, `Lists.test.tsx`

**Interfaces:**
- Consumes: Task 4 routes.
- Produces: `NewTaskForm({ projects, initialProject?, initialEpic?, initialSummary?, itemId?, onCreated(key), onCancel })`.

Rules: the form matches mockup `#s4` (required marks on Project, Type, Summary, Description, Done when, Owner, Waiting on; Epic picker lists the project's open epics plus "No epic"; Priority select; Refs as comma-separated text validated against the key pattern). Errors, exactly: `A summary is required.`, `Add a description: what this task is.`, `Add a "Done when" line.`, `Say who owns it.`, `Say who it waits on.`, `Refs look like ABC-123.` Task detail matches `#s3` right panel: header key + type + status pill, summary, `Epic <KEY> · owner <x> · waiting on <y> · reporter <z>`, Description with `Done when:` under it, Links table (each row opens its URL in a new tab), the reason line, actions: status menu only when the task has no links, `Confirm done` when `awaiting_confirmation`, `Cancel task` with a confirm step. Epic detail task list matches `#s3` left panel.

- [ ] **Step 1: Failing tests:** `test_new_task_form_required_fields_and_body`, `test_new_task_from_unfiled_row_links_item`, `test_link_to_task_menu_groups_by_epic`, `test_task_detail_shows_reason_and_links`, `test_status_menu_hidden_for_linked_task`, `test_confirm_done_button_only_when_awaiting`, `test_epic_detail_lists_tasks_and_add_task`, `test_needs_you_task_row_links_to_task`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4:** `bash scripts/test.sh` → PASS.
- [ ] **Step 5: Commit** `feat(web): task detail, new task form, epic task list and Unfiled linking`

### Task 8: Acceptance and docs

**Files:**
- Modify: `scripts/acceptance-local.sh` (after the existing step 6: create task `DEMO-…` under `DEMO-E1` using the write credentials the script already uses, `GET /api/projects/DEMO/tasks` shows it in the `DEMO-E1` lane, link one unfiled item to it, `GET /api/tasks/<key>` shows the link; the board counts the script already compares still match, since migrated and filed items each become one task), `README.md` ("Tasks" section: keys, prefixes, refs, lifecycle in five lines), `docs/connectors.md` (task prefix and refs)
- [ ] **Step 1:** Extend the script; run `bash scripts/acceptance-local.sh` → `ACCEPTANCE PASS`.
- [ ] **Step 2:** `bash scripts/test.sh` → PASS.
- [ ] **Step 3: Commit** `test: acceptance covers tasks; docs for tasks`

## Not in this plan (operator side, after merge)

- Applying `0002_tasks.sql` to the live database and deploying (owner's OK).
- Screenshots of every new screen at desktop and 390 px against the mockups.
- Writing tasks for already-approved plans, tagging cards and PRs with task keys, and proposing duplicate merges (a later step).
