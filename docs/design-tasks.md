# Loopboard Tasks: Jira-style Epics and Tasks (design)

Public copy of an approved design. Examples use the neutral project key `DEMO`.

## Why

Before this change a "task" in Loopboard was one **source item**: a Kanban card or a GitHub PR. That has three problems:

- The same unit of work counts twice when a Kanban card opens a PR (the card and the PR are two "tasks").
- A big epic shows **0 tasks** until someone opens a card or a PR, so its breakdown is invisible.
- Work with no code (a sign-off, a decision) can't be a task at all.

This design adds a **Task** between epics and items, modelled on Jira: its own key, a small set of required fields and a simple lifecycle. Source items become **links** on a task, the way Jira lists PRs in an issue's development panel.

## Goals

- A Task entity with key `<PROJECT>-<n>` (e.g. `DEMO-12`), separate from epic keys (`DEMO-E1`).
- Items link to tasks; epic progress counts tasks, not items.
- A Tasks board per project with one swimlane per epic, next to the existing epic board, which stays the home screen.
- Status moves by itself for any task with links; tasks without links move by hand.

## Non-goals

Sub-tasks, sprints, story points, estimates, due dates, custom workflows, comments, Jira import or sync. Manual status upkeep for coded work is an anti-goal: anything linked follows its sources.

## The Task

| Field | Required | Notes |
|---|---|---|
| key | auto | `<PROJECT>-<n>`; one counter per project, separate from the epic counter. |
| project | yes | |
| type | yes, default `task` | `task` or `bug`. |
| summary | yes | 1-300 characters. |
| description | yes | What the task is. Non-blank, max 2000. |
| done_when | yes | The acceptance criteria, one line. Non-blank, max 300. |
| epic | no | Parent epic in the same project. A task without an epic shows in a **No epic** swimlane (this replaces the old "standalone" filing). |
| owner | yes | Who does it (the assignee), free text up to 100, e.g. `coder` or `owner`. |
| waiting_on | yes while open | `agent:<name>`, `human:<name>` or `source:<name>`, as for epics and items. |
| status | manual, starts `todo` | `todo`, `in_progress`, `review`, `done`, `canceled`. Only used when the task has no live links (see Lifecycle), except `canceled`, which always wins. |
| priority | no, default `medium` | `high`, `medium`, `low`. |
| refs | no | Other keys that mean this task (e.g. another tracker's `OPS-8001`). Up to 10, each matching `^[A-Z][A-Z0-9]{1,9}-[0-9]+$`. |
| reporter, created_at, updated_at, last_activity_at | auto | Reporter is the principal that created it. |

## Lifecycle

Displayed statuses: **Todo → In progress → Review → Done**, plus Canceled (hidden from boards). Blocked and stalled are flags.

A task's **live links** are its linked items that are not `ignored` and whose category is not `canceled`. The item category uses the existing rule: a merged PR counts as `done` only once it is live; a Kanban card counts as done when the card is done.

1. Manual status `canceled` → **Canceled**.
2. **With live links** (automatic, in this order):
   - any link `in_progress` → **In progress**;
   - else any link `review` → **Review** (flag `merged_not_live` when a linked PR is merged but not live);
   - else every link `done` → **Done**;
   - else any link `blocked` → **In progress** with the blocked flag;
   - else → **Todo**.
   - Any blocked link sets `blocked`; one blocked with reason `needs_input` also sets `blocked_needs_input`.
3. **Without live links:** the manual status. A manual `done` that no human has confirmed shows as **Review** with flag `awaiting_confirmation` until a human confirms it. A human's own move to `done` confirms it at once.

Who is a human: a request signed in through Cloudflare Access, or an API token with the new `human` scope. Every other token is an agent.

A task is **stalled** when it is open and nothing moved (the task itself or any live link) for longer than the stall threshold: the smallest threshold among its links' sources, or, when it has no live links, the threshold of the `planned` pseudo-source: 7 days by default, configurable with `PUT /api/sources/planned`. An unstarted planned task therefore shows as stalled after a week, which is how a stale plan surfaces without flooding the list with work that isn't late.

## Epics on top of tasks

- The epic column is derived from its tasks with the same rules as before, now over task statuses: any task in progress → In progress; else any in review → Review; all done → Done; no tasks → the epic's manual column (Done if a human confirmed it).
- Progress = done tasks / tasks (canceled tasks excluded).
- Epic flags are the union of its tasks' flags; `review_owner` is `human` when any task in review waits on a human or awaits confirmation.

## Linking items to tasks

For an item that is **new or unfiled** (an existing filing made through the API always wins, as before):

1. Title prefix `[DEMO-12] ` → link to that task. A merged-away task resolves to the task it was merged into.
2. Else a **ref** of an open task in the item's project appears in the title as a whole token (`fix(OPS-8001): …` matches ref `OPS-8001`; `OPS-80` does not match inside `OPS-8001`) → link to that task.
3. Else title prefix `[DEMO-E5] ` → create a new task under that epic from the item (summary = item title, description = `Created from <url or source:external_id>`, done_when = `The linked work is live.`, owner = item owner or the source name, reporter = the ingesting principal) and link the item.
4. Else the item stays **Unfiled**.

Unknown keys never fail an ingest. Linking an item to a task sets its project and epic to the task's.

## Merging tasks

Merging task A into task B moves A's links to B, adds A's key to B's refs, marks A canceled with `merged_into = B`. Cards and PRs already titled with A's key keep linking (to B).

## Screens

- **Board** gets an **Epics | Tasks** switch. Epics is the existing board.
- **Tasks board**: always one project; columns Todo, In progress, Review, Done; one swimlane per epic of that project (epics in board order, canceled and hidden-done epics left out), then **No epic**. Lanes fold; each lane header shows the epic key, title and progress. Task cards show key, type, summary, a links summary (`🗂 N card`, `⑂ N PR` plus the most advanced state), who it waits on and for how long, and flags. Cards of tasks without links can be dragged between columns; linked cards can't and open the task. Done tasks hide after 7 days. On a phone: one column at a time, epics as small headings.
- **Task detail**: fields, description and Done when, the links (each opens its source), a one-line reason for the current status, actions (move, confirm done, cancel) and the activity log.
- **Epic detail**: description, its tasks as a list (key, summary, link chips, status, owner) with **+ Add task**, and the activity log.
- **New task form**: the required fields marked; Epic is a picker; the created key is shown.
- **Unfiled**: per item, *Link to task ▾* (open tasks of the item's project, grouped by epic), *New task from this…* (the form prefilled with the item title, linking it on create) and *Ignore*.
- **Needs you / Stalled**: list tasks instead of raw items.

## Migration of existing data

Expand only:
1. Add the `tasks` table and `items.task_id`.
2. Backfill: every item filed to an epic or standalone gets its own task (one task per item), under the same epic or with no epic, with description `Migrated from <url or source:external_id>` and done_when `The linked work is live.`, reporter `migration`.
3. Duplicates (a Kanban card and the PR it opened) are merged afterwards through the API, one decision at a time.
The old `filing` values stay readable; dropping them is a later release.

## Risks

- Plans drift from tasks: unstarted tasks go stalled, which surfaces them.
- Auto-tasks from epic-only tags can re-create the double count: tag with task keys once tasks exist, and merge duplicates.
- Ref false matches: whole-token matching only, and only within the item's project.
