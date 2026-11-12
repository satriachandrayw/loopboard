# Connectors

A connector reads one external source and pushes its items to Loopboard through
`POST /api/ingest`. Run one with `loopboard sync <connector> --config PATH`.

## Contract

- Abilities are read-only: `ABILITIES = ("read",)`. A connector never writes to its source.
- Find/fetch: list the source's items, then fetch the detail needed per item. Any failure,
  unparseable output or missing field fails the whole run and nothing is posted.
- Map: each source record becomes an `Item` (`source`, `external_id`, `title`, `url`,
  `status_category`, `raw_status`, `owner`, `waiting_on`, `blocked_reason`, `next_step`,
  `project_key`, `epic_key`, `last_activity_at`, `merged_at`, `live_at`).
- `last_activity_at` is the newest activity timestamp the source offers, as ISO 8601 with `Z`
  or an offset. Ingest skips a payload older than the stored value.
- Upsert-only: a listing never cancels, unfiles or deletes an item that is absent from it.
  A non-zero exit or unparseable output posts nothing.
- Free text (bodies, comments, summaries, block reasons) is never read or sent.

## Ingest payload

```json
{"source": "kanban", "items": [{"external_id": "7", "title": "Task 7", "url": null,
  "status_category": "todo", "raw_status": "todo", "owner": "agent:builder",
  "waiting_on": "agent:builder", "blocked_reason": null, "next_step": null,
  "project_key": "DEMO", "last_activity_at": "2025-11-12T09:00:00Z"}]}
```

At most 100 items per request; the runner splits larger listings. `epic_key` is omitted when
unset so ingest keeps any existing filing. Open items need `waiting_on` of the form
`agent:<name>`, `human:<name>` or `source:<name>`. The response is
`{"accepted","created","updated","skipped_older"}`. A token bound to another source gets 403.

## Hermes Kanban mapping

Timestamps from Hermes are epoch seconds and are emitted as UTC ISO. `last_activity_at` is the
newest of created, started, completed and every event time. `owner` is `agent:<assignee>` or
null; `next_step` is always null. Tenant maps to `project_key` through `[kanban.tenants]`.

| Status | Category | `waiting_on` |
| --- | --- | --- |
| triage | todo | `human:<human>` |
| todo, ready | todo | `agent:<assignee>` (`source:kanban` if unassigned) |
| running | in_progress | `agent:<assignee>` |
| review | review | `human:<human>` |
| blocked, newest blocked event kind `needs_input` | blocked | `human:<human>` |
| blocked, any other kind | blocked | `source:kanban` |
| done | done | null |
| archived | canceled | null |

An unknown status fails the run.

## GitHub pull requests

(Filled in by the GitHub connector task.)

## CLI

```
loopboard sync kanban --config PATH [--board SLUG] [--cli-replay DIR] [--dry-run]
```

It prints one JSON summary line, for example
`{"connector":"kanban","collected":8,"accepted":8,"created":8,"updated":0,"skipped_older":0,"posts":1,"dry_run":false}`.
`--cli-replay DIR` reads `list.json` and `show-<id>.json` from DIR instead of calling `hermes`.
`--dry-run` collects and maps but posts nothing and needs no token.

| Exit | Meaning |
| --- | --- |
| 0 | ok (an empty listing posts nothing) |
| 1 | source failure, nothing posted |
| 2 | config or token error |
| 3 | ingest rejected (for example 403 or 422) |

## Config keys

- `[loopboard] url`: base URL; posts go to `<url>/api/ingest`.
- `[loopboard] token_env`: name of the environment variable holding the bearer token.
- `[general] human`: name used in `human:<human>` (for example `owner`).
- `[kanban] board`: optional Hermes board slug.
- `[kanban.tenants]`: Hermes tenant to project key (for example `demo = "DEMO"`).

`config.toml` is git-ignored; copy `connectors/config.example.toml`.
