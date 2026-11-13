# API

Every route is under `/api` and needs authentication. There is no anonymous mode.
Timestamps in responses are epoch seconds (UTC). Timestamps in requests are ISO 8601 with an
explicit offset or `Z`; a naive timestamp is 422. Request bodies reject unknown fields (422).

## Authentication and scopes

- Bearer token: `Authorization: Bearer lb_...`. Tokens are created with
  `worker/scripts/make_token.py` (see [install.md](install.md)). Each has a comma list of scopes
  (`ingest`, `read`, `write`, `human`) and may be bound to one `source`. `human` goes with
  `read`/`write` (never `ingest`) and marks the token as a person's.
- Humans and agents: a request signed in through Cloudflare Access, or with a token carrying the
  `human` scope, is a human. Every other token is an agent. Only a human confirms a task done.
- Cloudflare Access: when `ACCESS_TEAM_DOMAIN` and `ACCESS_AUD` are set, a request with a valid
  `Cf-Access-Jwt-Assertion` (RS256, audience `ACCESS_AUD`) is accepted with all scopes. The
  `Cf-Access-Authenticated-User-Email` header alone is never trusted.
- Status codes for every route: `401` no or invalid credentials, `403` the credentials lack the
  scope (or an ingest token bound to another source or to none), `422` invalid body or parameters.
- Every `/api/*` response carries `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`.

## Ingest (scope `ingest`)

### POST /api/ingest

Body: `{"source": "kanban", "items": [Item, ...]}`, at most 100 items. `source` matches
`^[a-z][a-z0-9_-]{1,31}$`. An `Item` has `external_id`, `title`, `status_category`
(`backlog|todo|in_progress|blocked|review|done|canceled`), `last_activity_at`, and optionally
`url` (http:// or https:// only), `raw_status`, `owner`, `waiting_on` (`agent:<name>`, `human:<name>` or `source:<name>`;
required on open items), `blocked_reason` (`needs_input|other`), `next_step`, `project_key`,
`epic_key`, `task_key` (`^[A-Z][A-Z0-9]{1,9}-[0-9]+$`), `merged_at`, `live_at`. Absent keys leave
the item's filing unchanged.

Only a new item or one stored as `unfiled` is linked to a task, in this order: `task_key` names a
task (a merged-away task resolves to its survivor); else a ref of an open task of the item's
project appears in the title as a whole token; else `epic_key` names an open epic, and a new task
is made under it from the item (reporter = the ingest token). The item takes the task's project
and epic (`filing` `epic`, or `standalone` for a task with no epic). A stored `epic`, `standalone`
or `ignored` filing is never overwritten: a human or Hermes filing wins. Linking an existing unfiled
item writes an `item.filed` event with the `task_key` (the other changed fields go in
`item.updated`); a new item's link is in its `item.created` event. Touched epics are recomputed.
An unknown or canceled epic or task is not an error: the item is ingested as if it had no key (new
items land in `unfiled`), it is counted in `unknown_epic` or `unknown_task`, and the rest of the
request still commits. An unknown `project_key` is still 422 for the whole request.

Response 200: `{"accepted","created","updated","skipped_older","unknown_epic","linked_task",
"auto_tasks","unknown_task"}`. `unknown_epic` / `unknown_task` count the items whose key was
unknown or canceled, `linked_task` the items linked by key or ref, `auto_tasks` the tasks made
from epic keys (each 0 when none). Ingest is idempotent; a
payload older than the stored `last_activity_at` is skipped. 403 if the token is bound to another source or is an ingest token bound to no source.
See [connectors.md](connectors.md).

## Reads (scope `read`)

### GET /api/health

`{"ok": true, "principal": "<name>"}`. 200.

### GET /api/projects

List of `{id, key, name, created_at}`. 200.

### GET /api/board

Query: `project` (key), `waiting_on` (`agent|human|source`). Response 200:
`{"columns": [{column, label, count, warn, cards: [...]}]}` for backlog, todo, in_progress,
review, done. A card has `id, key, title, goal, project_key, column, stage, progress, owner,
waiting_on, waiting_since, stalled, flags, review_owner`. Canceled epics and Done epics older
than 7 days are hidden. `goal` (the description) is null on epics created before it was required.

### GET /api/needs-you

Query: `project` (key). Open epics waiting on a human, awaiting approval or confirmation, merged
but not live, blocked on input or in review by a human (`kind: "epic"`), and open tasks waiting on
a human or awaiting your confirmation (`kind: "task"`, with `epic_key`; a task with no epic also
lists merged, not live and blocked on input). Oldest first. With `project`, only that project. 200.

### GET /api/stalled

Query: `waiting_on` (`agent|human|source`), `project` (key). Stalled epics (`kind: "epic"`) and
stalled tasks (`kind: "task"`, with `epic_key`; tasks of canceled epics are left out). A task
stalls when it is open and neither it nor a live link moved for longer than the smallest stall
threshold of its links' sources. A task with no live links (planned work nobody has started) uses
the threshold of the `planned` source instead, 168 h (7 days) unless set with
`PUT /api/sources/planned`. 200.

### GET /api/unfiled

Query: `project` (key). Non-canceled items that are not yet filed, oldest first. A row has
`id, source, external_id, title, url, owner, waiting_on, last_activity_at, project_key` (null when
the item names no project), `status_category`, `category` (the effective category: a merged and
live review item counts as `done`), `merged_at, live_at`. 200.

### GET /api/epics/{key}

Epic card (its `column` is the derived board column, the only column field) plus links, `tasks`
(the epic's non-canceled tasks as task cards, by key), `relations` and the newest 50 `events`
(of the epic, its tasks and their linked items). 200, or 404 if the epic does not exist.

The epic column is derived from its tasks: any task in progress → in_progress; else any in review
→ review; all done → done; no tasks → the manual column (done if a human confirmed it).
`progress` is done tasks / tasks, canceled tasks left out.

### GET /api/projects/{project_key}/tasks

The Tasks board of one project: `{"project", "columns": ["todo","in_progress","review","done"],
"lanes": [{"epic": {key, title, progress} | null, "tasks": {<column>: [task card...]}}]}`. One lane
per shown epic of the project in board order (canceled and hidden Done epics left out), then the
No-epic lane (`epic: null`). Canceled tasks and tasks Done for more than 7 days are left out.
A task card has `id, key, type, summary, description, done_when, project_key, epic_key, status,
flags, reason, priority, owner, waiting_on, waiting_since, stalled, refs, reporter, links_summary,
last_activity_at`. `links_summary` maps each source of the live links to `{count, state}` with the
most advanced state (`todo, blocked, open, running, review, merged, done, live`). 200, 404 unknown
project.

### GET /api/tasks/{key}

A task card plus `merged_into` (key or null), `done_confirmed_at`, `created_at`, `updated_at`,
`links` (linked items: `id, ref, source, external_id, title, url, status_category, category,
owner, waiting_on, next_step, last_activity_at, merged_at, live_at, filing, stalled`) and the
newest 50 `events` of the task and its linked items. 200, 404 unknown task.

Task status (`status`, with a one-line `reason`): a canceled task is `canceled` (`Canceled`, or
`Merged into <KEY>`). A task with live links (not ignored, not canceled at the source) follows
them: any in progress → `in_progress`; else any in review → `review` (flag `merged_not_live` when a
linked PR is merged but not live); else all done → `done`; else any blocked → `in_progress` with
the `blocked` flag; else `todo`. Without live links the manual status counts (`Moved by hand`); a
manual `done` no human confirmed shows as `review` with flag `awaiting_confirmation`.

## Writes (scope `write`)

Create, patch and confirm-done on an epic return the epic card as `GET /api/epics/{key}` shows it
(its `epic` object: derived `column` only, no stored column fields).

### POST /api/projects

Body: `{"key": "DEMO", "name": "Demo"}`; key matches `^[A-Z][A-Z0-9]{1,9}$`. 201, 409 if the
key exists.

### POST /api/projects/{project_key}/epics

Body: `{"title", "goal", "stage"? (idea|spec|plan|build|review|ship), "owner"?, "next_step"?,
"waiting_on", "home_url"?, "spec_url"?, "plan_url"?, "manual_column"? (backlog|todo|canceled)}`. URL fields accept only `http://` or `https://` (else 422).
`goal` is the epic's description (shown as "Description" in the UI): required, at most 2000
characters, stored stripped; missing, null, empty or whitespace-only is 422.
`waiting_on` (`agent:<name>`, `human:<name>` or `source:<name>`) is required unless
`manual_column` is `canceled` (422 otherwise). Epic keys are `<PROJECT>-E<n>`, numbered per
project from 1. 201, 404 unknown project.

### PATCH /api/epics/{key}

Body: any of the epic fields above; null is rejected for fields that cannot be null and an empty
body is 422. `goal` cannot be set to null, empty or whitespace-only (422); a given `goal` is stored stripped.
`waiting_on` cannot be set to null, and a canceled epic cannot be reopened without
one, unless the epic stays canceled (422). 200, 404 unknown epic. Agents never set a column other than backlog, todo or canceled.

### POST /api/epics/{key}/confirm-done

No body, but the request must carry `Content-Type: application/json` (415 otherwise), so a
cross-site form cannot post it with the Access cookie. Confirms an epic that has no tasks is
done (an epic with tasks follows them). 200, 404 unknown epic.

### POST /api/items/{item_id}/filing

Body: `{"filing": "epic|standalone|ignored", "epic_key"?, "project_key"?}`. `epic_key` is
required for `epic`; `standalone` needs a project. Every filed item belongs to a task: if the
item's task is in the same project it moves to that epic (or to No epic for `standalone`),
otherwise a new task is made from the item (summary = title, description `Created from <url or
source:external_id>`, done_when `The linked work is live.`). `ignored` unlinks the item. Returns
the item row. 200, 404 unknown item or epic, 422 invalid.

### POST /api/items/{item_id}/deployed

Body: `{"live_at": "<ISO 8601 with offset>"}`. Records deploy evidence on a merged PR item.
200, 404 unknown item, 422 if the item has no merged PR.

### POST /api/relations

Body: `{"from_type": "epic|item|task", "from_id", "to_type": "epic|item|task", "to_id"}`; creates a
`blocks` relation. 201, 404 unknown subject, 409 if it exists, 422 if it points at itself.

### DELETE /api/relations/{relation_id}

204, 404 unknown relation.

### PUT /api/sources/{name}

Body: `{"stall_hours": 24}` (greater than 0, at most 8760). Sets the stall threshold for a
source. `name` matches `^[a-z][a-z0-9_-]{1,31}$` (else 422). The name `planned` is a pseudo-source:
it sets the stall threshold for tasks with no live links (default 168 h, 7 days). 200.

## Tasks (scope `write`)

Task keys are `<PROJECT>-<n>`, numbered per project from 1, separate from epic keys
(`<PROJECT>-E<n>`). Task routes return the task card as `GET /api/projects/{project_key}/tasks`
shows it. Every task write records events (`task.created`, `task.updated`, `task.status_changed`,
`task.done_confirmed`, `task.merged`, `item.linked`, `item.unlinked`) and recomputes the epics it
touches.

### POST /api/projects/{project_key}/tasks

Body: `{"summary" (1-300), "description" (max 2000), "done_when" (max 300), "owner" (max 100),
"waiting_on", "type"? (task|bug, default task), "priority"? (high|medium|low, default medium),
"epic_key"?, "refs"? (up to 10 keys like `OPS-8001`), "item_id"?}`. Strings are stripped; a blank
required field is 422. `epic_key` must be an epic of the project (422; 404 unknown). With
`item_id` the item is linked to the new task. The status starts at `todo`; the reporter is the
caller. 201, 404 unknown project or item, 409 if a concurrent create took the key.

### PATCH /api/tasks/{key}

Body: any of `summary, description, done_when, owner, waiting_on, type, priority, refs, epic_key`
(`epic_key: null` moves the task to No epic; its linked items follow). Null is 422 for fields that
cannot be null; `waiting_on` cannot be null while the task is open; an empty body is 422.
200, 404 unknown task or epic.

### POST /api/tasks/{key}/status

Body: `{"status": "todo|in_progress|review|done|canceled"}`. A task with live links follows them:
any status but `canceled` is 422 `status follows its links`. A human's move to `done` confirms it;
an agent's leaves the task in review awaiting confirmation. A merged task stays canceled (422).
200, 404 unknown task.

### POST /api/tasks/{key}/confirm-done

No body, `Content-Type: application/json` required (415 otherwise). A human confirms a task an
agent moved to done. 200, 403 for an agent, 404 unknown task, 422 if the task is not awaiting
confirmation.

### POST /api/tasks/{key}/merge

Body: `{"into": "<KEY>"}`. Moves the task's links to `into`, adds the key (and its refs) to the
survivor's `refs` and cancels the task with `merged_into`. Items titled with the old key keep
linking to the survivor. Returns the survivor. 200, 404 unknown task, 422 across projects, into
itself, from or into a canceled task, or when the survivor's refs would exceed 10 (`merged refs
would exceed 10; trim the survivor's refs first`).

### POST /api/items/{item_id}/link

Body: `{"task_key": "<KEY>"}`. Links the item to the task; the item takes the task's project and
epic (`filing` `epic`, or `standalone` for a task with no epic). A merged-away key links to the
task it was merged into, as ingest does. Returns the item row. 200, 404 unknown item or task, 422
canceled task.

### POST /api/items/{item_id}/unlink

No body. The item goes back to Unfiled (`filing` `unfiled`, no task or epic). Returns the item
row. 200, 404 unknown item.
