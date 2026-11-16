# Needs You Questions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Needs you row says what kind of answer it needs, the question, short context and how to answer; the task page puts that answer box on top; nothing can wait on a human without a question.

**Architecture:** Migration `0003` adds ask fields to `tasks` and `epics` (expand-only). Models validate them; writes enforce "waiting on a human needs a question". `reads.needs_you` returns a richer row (kind of answer, question, how, reply code, context) and computes a standard question for rows that have none, folds merged-not-live work into one Release row per project, and drops epic rows that only repeat their tasks. The web list groups rows by answer kind with a Copy button; the task page shows the answer box first; desktop gets a list + detail split.

**Tech Stack:** Python 3.13 FastAPI on Cloudflare Workers + D1 (pydantic), pytest; React + TypeScript, Vitest + Testing Library.

**Spec:** `docs/design-needs-you-questions.md` (approved 16 Nov 2026). Its decisions are restated in Global Constraints.

## Global Constraints

- **Migration `worker/migrations/0003_ask_fields.sql`, expand-only:** `tasks` gains `question TEXT`, `answer_how TEXT`, `reply_code TEXT`, `ask_kind TEXT`, `not_before INTEGER`; `epics` gains `question TEXT`, `answer_how TEXT`, `reply_code TEXT`. No backfill, no other schema change.
- **Model fields** (stripped strings, blank → treated as missing): `question` ≤ 300, `answer_how` ≤ 200, `reply_code` ≤ 80, `ask_kind` ∈ `decide|review|release|confirm` (default `decide` when a question is set), `not_before` epoch seconds or null. `TaskIn`, `TaskPatch`, `EpicIn`, `EpicPatch` accept them; patches may set them to null except where the rule below forbids it.
- **The rule (422, message exactly `A task waiting on a human needs a question and how to answer.` / `An epic waiting on a human needs a question and how to answer.`):**
  - `create_task` / `create_epic` when `waiting_on` starts with `human:` and `question` or `answer_how` is missing;
  - `patch_task` / `patch_epic` when the patch sets `waiting_on` to `human:…`, or touches `question`/`answer_how`, and the resulting row waits on a human without both;
  - not applied to rows created by ingest (connector auto tasks) and not to patches that touch neither field (existing rows keep working until the operator backfills them).
- **`GET /api/needs-you` row shape** (every row):
  `{kind: "task"|"epic"|"release", id, ref, title, project_key, epic_key, url, waiting_on, waiting_since, reasons, ask_kind: "decide"|"review"|"release"|"confirm"|"later", question, answer_how, reply_code, context, auto, missing_question, items}`
  - `context`: the task description (or epic goal), plain text, unchanged; the client clamps it to 2 lines.
  - `auto`: true when the question was computed, not stored. `missing_question`: true only for the "no question recorded" fallback.
  - `items`: only on `release` rows: `[{ref, title, url, project_key}]` of the merged-not-live links, oldest first.
  - `reasons` stays for backward compatibility.
- **Merged-not-live always folds** (review round 1): every open task's merged-not-live links are `items` of its project's Release row, whether or not the task also gets its own row and regardless of `not_before`. The task's own ask below is resolved with the `merged_not_live` flag and the merged links ignored.
- **Ask resolution per task row, first match wins:**
  1. `not_before` > now → `ask_kind: "later"` (question/how as resolved below; only the task's own row moves).
  2. stored `question` → its stored `ask_kind` (default `decide`), `answer_how`, `reply_code`.
  3. flag `awaiting_confirmation` → `confirm`, question `The agent says this is done. Is it?`, answer_how `Press Confirm done, or tell your agent what is missing.`, reply_code null.
  4. flag `merged_not_live` → never the task's own ask: its links fold into the project's Release row (above).
  5. flag `blocked_needs_input` with a linked kanban item `<id>` → `decide`, question `What should card <id> do next?`, answer_how `Read the block reason on the card, then reply to your agent:`, reply_code `<id>: <answer>`.
  6. a linked open GitHub PR item `<owner>/<repo>#<n>` and the task waits on a human → `review`, question `Merge PR <repo>#<n>?`, answer_how `Reply to your agent:`, reply_code `merge <repo>#<n>`.
  7. a linked kanban item in review and the task waits on a human → `review`, question `Approve card <id>?`, answer_how `Reply to your agent:`, reply_code `push <id>`.
  8. waits on a human, nothing above → `decide`, question `No question recorded yet.`, answer_how `Ask your agent about this task:`, reply_code `<KEY>?`, `missing_question: true`. No rule 8 row when the task's only open work is merged-not-live links and it has no stored question: the Release row covers it.
- **Release rows:** one per project with merged-not-live links on open tasks: `id` the project id, `ref` `release:<PROJECT_KEY>`, title `<Project name>: 1 change merged, not live` / `<Project name>: N changes merged, not live` (N ≥ 2), `waiting_on` null, question `Release <Project name> to its live branch?`, answer_how `Reply to your agent:`, reply_code `release <project key lowercased>`, `waiting_since` = oldest link, `auto: true`.
- **Epic rows** appear only when the epic's own `waiting_on` is a human and the epic is not done/canceled: stored question or rule 8 wording (`reply_code` `<EPIC_KEY>?`). Task-derived reasons no longer create epic rows; task rows always carry their own flags (remove the "an epic's row already carries these" skip).
- **Order:** groups decide, review, release, confirm, later; oldest `waiting_since` first inside each. The API returns rows already in that order.
- **Task detail** (`GET /api/tasks/{key}`) adds `question`, `answer_how`, `reply_code`, `ask_kind`, `not_before` and `epic_next_step`.
- **UI copy (exact):** group headings `Decide`, `Review`, `Release`, `Confirm`, `Later`; header subline `<n> to answer now · <m> later · oldest first in each group`; row link `Context and details ›`; copy button `Copy` → `Copied` for 2 s (`Copy failed` for 2 s when the clipboard write fails); answer box heading `Your answer`; missing-question badge `No question recorded`; form labels `Question for you`, `How to answer`, `Reply code (optional)`, `Kind`, `Not before (optional)`; form error `Write the question and how to answer: this task waits on a human.`; `Confirm done` shows only on rows whose `reasons` include `awaiting your confirmation`; the nav badge counts rows that aren't `later`.
- Visuals follow the approved mockup (dark theme, coloured kind label: Decide amber, Confirm teal, Release indigo, Review indigo-outline, Later grey; question bold one line with a leading amber `?`; context 2 lines muted; reply code in a monospace chip with Copy). Phone 390 px and desktop.
- Repo rules from earlier plans hold: neutral names (`owner`, `DEMO`), no deploy/push, `bash scripts/test.sh` is the gate, `bash scripts/acceptance-local.sh` must print `ACCEPTANCE PASS`.

## Review Focus

- Creating a task waiting on a human without a question → 422 with the exact message; the same body with `question` + `answer_how` → 201 (Task 1 `test_human_task_needs_question`).
- Patching only `priority` on an old human task without a question still succeeds (Task 1 `test_patch_untouched_ask_fields_keeps_old_rows_working`).
- Two PRs merged into a non-live branch in one project → one Release row listing both, no per-task rows, no epic row (Task 2 `test_release_row_folds_merged_not_live`).
- An epic whose only reason was a task's awaiting confirmation no longer appears; the task row does (Task 2 `test_epic_rows_only_for_own_human_wait`).
- Stored question beats the computed PR question (Task 2 `test_stored_question_wins`); `not_before` in the future → `later` (Task 2 `test_not_before_moves_to_later`).
- Copy button copies `reply_code`, not the label (Task 3 `test_copy_copies_reply_code`).
- New task form: waiting on a human with an empty question shows the error and posts nothing (Task 4 `test_human_task_form_requires_question`).

---

### Task 1: Migration, models and the write rule

**Files:** create `worker/migrations/0003_ask_fields.sql`, `worker/tests/test_migration_0003.py`; modify `worker/src/loopboard/model.py`, `worker/src/loopboard/writes.py` (`TASK_FIELDS`, `EPIC_FIELDS`, create/patch for tasks and epics), `worker/tests/test_model.py`, `worker/tests/test_task_writes.py`, `worker/tests/test_writes.py`.

- [ ] Write failing tests: migration applies on a DB with 0002 data and keeps every row (counts before = after); model length/enum limits; `test_human_task_needs_question`, `test_human_epic_needs_question`, `test_patch_to_human_needs_question`, `test_patch_untouched_ask_fields_keeps_old_rows_working`, ingest auto task with `human:` waiting is still created.
- [ ] Implement the migration, fields and the rule; ask fields are included in `task.created`/`task.updated` and epic event payloads like the other fields.
- [ ] `bash scripts/test.sh`; commit `feat(worker): ask fields and the waiting-on-a-human rule`.

### Task 2: Reads: the new Needs you row

**Files:** modify `worker/src/loopboard/reads.py` (`needs_you`, task detail, card loaders as needed), `worker/tests/test_reads.py`, `docs/api.md`.

- [ ] Write failing tests for each ask-resolution rule (1-8), the Release fold, epic-row rule, ordering, task detail extra fields, and `test_stored_question_wins`, `test_not_before_moves_to_later`, `test_release_row_folds_merged_not_live`, `test_epic_rows_only_for_own_human_wait`.
- [ ] Implement as pure helpers (`resolve_ask(task_row, links, now)`, `release_rows(...)`) so they're unit-testable without D1.
- [ ] Update `docs/api.md` (row shape, rule, new fields); `test_api_doc.py` must pass.
- [ ] `bash scripts/test.sh`; commit `feat(worker): needs-you rows carry their question`.

### Task 3: Web: Needs you list, task page answer box, desktop split

**Files:** modify `web/src/types.ts`, `web/src/screens/NeedsYou.tsx`, `web/src/screens/TaskDetail.tsx`, `web/src/index.css`; create `web/src/components/AnswerBox.tsx`, `web/src/components/CopyCode.tsx`, `web/src/screens/NeedsYou.test.tsx`; extend `web/src/screens/TaskDetail.test.tsx`.

- [ ] Tests first: grouping and order, header subline, Later collapsed with its count, row shows kind label + question + 2-line context + how + reply code, `missing_question` badge, Release row expands inline to its items (links open in a new tab), Confirm rows show `Confirm done` (calls the existing confirm endpoint), `test_copy_copies_reply_code`, task page shows `Your answer` box first and the epic's next step.
- [ ] Desktop ≥ 1100 px: list left (~470 px), selected row detail right (task: same AnswerBox + description, done-when, links, epic next step, activity; release: its items); route `#/needs-you/<ref>` keeps the selection. Below 1100 px a row links to the task page as today.
- [ ] `bash scripts/test.sh`; commit `feat(web): needs-you questions, answer box and desktop split`.

### Task 4: New task form, acceptance and docs

**Files:** modify `web/src/components/NewTaskForm.tsx` (+ test), `web/src/components/NewEpicForm.tsx` (+ test), `scripts/acceptance-local.sh`, `docs/api.md`.

- [ ] Forms: when "waiting on" is the human, show `Question for you`, `How to answer`, `Reply code (optional)`, `Kind` (task form), `Not before (optional)` (task form, date → epoch at local midnight); `test_human_task_form_requires_question` and the epic equivalent.
- [ ] Acceptance script: one create waiting on a human without a question → 422; with one → 201; `GET /api/needs-you` row carries `question` and `ask_kind`.
- [ ] `bash scripts/test.sh` and `bash scripts/acceptance-local.sh` (`ACCEPTANCE PASS`); commit `feat: ask fields in forms; acceptance covers the rule`.

## Not in this plan (operator side, after merge)

- Rehearse `0003` on a copy of live data; deploy with the migration (sync paused, time-travel bookmark).
- Backfill the human-waiting rows on the live board (move existing "question" text out of descriptions into the new fields, set `not_before` on dated asks), via the operator's write tool.
- Update the operator's write tool, daily triage prompt and the Needs you digest to use the new fields.
