# API

Every route is under `/api` and needs authentication. There is no anonymous mode.
Timestamps in responses are epoch seconds (UTC). Timestamps in requests are ISO 8601 with an
explicit offset or `Z`; a naive timestamp is 422. Request bodies reject unknown fields (422).

## Authentication and scopes

- Bearer token: `Authorization: Bearer lb_...`. Tokens are created with
  `worker/scripts/make_token.py` (see [install.md](install.md)). Each has a comma list of scopes
  (`ingest`, `read`, `write`) and may be bound to one `source`.
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
`epic_key`, `merged_at`, `live_at`. Absent `epic_key` leaves the item's filing unchanged.

`epic_key` files the item under that epic (`filing` `epic`, project from the epic) only when the
item is new or stored as `unfiled`. A stored `epic`, `standalone` or `ignored` filing is never
overwritten by `epic_key`: a human or Hermes filing wins. Filing an existing unfiled item this way
writes an `item.filed` event (the other changed fields go in `item.updated`); a new item's filing is
in its `item.created` event. The epic's column is then recomputed. An `epic_key` naming no epic, or
an epic whose manual column is `canceled`, is not an error: the item is ingested as if it had no
`epic_key` (new items land in `unfiled`), it is counted in `unknown_epic`, and the rest of the
request still commits. An unknown `project_key` is still 422 for the whole request.

Response 200: `{"accepted","created","updated","skipped_older","unknown_epic"}`. `unknown_epic`
counts the items whose `epic_key` was unknown or canceled (0 when none). Ingest is idempotent; a
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
review, done. A card has `id, key, title, project_key, column, stage, progress, owner,
waiting_on, waiting_since, stalled, flags, review_owner`. Canceled epics and Done epics older
than 7 days are hidden.

### GET /api/needs-you

Query: `project` (key). Open epics and standalone items waiting on a human, plus epics awaiting
approval or confirmation or merged but not live. Oldest first. With `project`, only epics and
standalone items of that project. 200.

### GET /api/stalled

Query: `waiting_on` (`agent|human|source`), `project` (key; an item counts for its own project or
its epic's). Stalled epics and items (filed to an epic or standalone). 200.

### GET /api/unfiled

Query: `project` (key). Non-canceled items that are not yet filed, oldest first. A row has
`id, source, external_id, title, url, owner, waiting_on, last_activity_at, project_key` (null when
the item names no project), `status_category`, `category` (the effective category: a merged and
live review item counts as `done`), `merged_at, live_at`. 200.

### GET /api/epics/{key}

Epic card (its `column` is the derived board column, the only column field) plus `goal`, links, `tasks` grouped by column, `relations` and the newest 50 `events`.
200, or 404 if the epic does not exist.

## Writes (scope `write`)

Create, patch and confirm-done on an epic return the epic card as `GET /api/epics/{key}` shows it
(its `epic` object: derived `column` only, no stored column fields).

### POST /api/projects

Body: `{"key": "DEMO", "name": "Demo"}`; key matches `^[A-Z][A-Z0-9]{1,9}$`. 201, 409 if the
key exists.

### POST /api/projects/{project_key}/epics

Body: `{"title", "goal"?, "stage"? (idea|spec|plan|build|review|ship), "owner"?, "next_step"?,
"waiting_on", "home_url"?, "spec_url"?, "plan_url"?, "manual_column"? (backlog|todo|canceled)}`. URL fields accept only `http://` or `https://` (else 422).
`waiting_on` (`agent:<name>`, `human:<name>` or `source:<name>`) is required unless
`manual_column` is `canceled` (422 otherwise). Epic keys are `<PROJECT>-E<n>`, numbered per
project from 1. 201, 404 unknown project.

### PATCH /api/epics/{key}

Body: any of the epic fields above; null is rejected for fields that cannot be null and an empty
body is 422. `waiting_on` cannot be set to null, and a canceled epic cannot be reopened without
one, unless the epic stays canceled (422). 200, 404 unknown epic. Agents never set a column other than backlog, todo or canceled.

### POST /api/epics/{key}/confirm-done

No body, but the request must carry `Content-Type: application/json` (415 otherwise), so a
cross-site form cannot post it with the Access cookie. A human confirms an epic without code is
done. 200, 404 unknown epic.

### POST /api/items/{item_id}/filing

Body: `{"filing": "epic|standalone|ignored", "epic_key"?, "project_key"?}`. `epic_key` is
required for `epic`; `standalone` needs a project. 200, 404 unknown item or epic, 422 invalid.

### POST /api/items/{item_id}/deployed

Body: `{"live_at": "<ISO 8601 with offset>"}`. Records deploy evidence on a merged PR item.
200, 404 unknown item, 422 if the item has no merged PR.

### POST /api/relations

Body: `{"from_type": "epic|item", "from_id", "to_type": "epic|item", "to_id"}`; creates a
`blocks` relation. 201, 404 unknown subject, 409 if it exists, 422 if it points at itself.

### DELETE /api/relations/{relation_id}

204, 404 unknown relation.

### PUT /api/sources/{name}

Body: `{"stall_hours": 24}` (greater than 0, at most 8760). Sets the stall threshold for a
source. `name` matches `^[a-z][a-z0-9_-]{1,31}$` (else 422). 200.
