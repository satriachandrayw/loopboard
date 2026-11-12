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

The title is truncated to 300 characters. An assignee that does not match the worker name
pattern (`[A-Za-z0-9._-]{1,64}`) is treated as unassigned: `owner` is null and `waiting_on` falls
back to `source:kanban` where it would have been the agent.

Known limitation (parked): items are keyed by `(kanban, task id)`, so syncing two Kanban boards
whose task ids overlap makes them collide and overwrite each other. Sync one board per Loopboard
instance until board-qualified ids are added.

## GitHub pull requests

```
loopboard sync github --config PATH [--dry-run]
```

Lists the pull requests of each repo in `[github.repos]`, most recently updated first, skips those not updated within `lookback_days` (default 14), and posts them as source `github`. The listing is paged (`per_page=100`, `page=1, 2, …`) until a page is empty or shorter than 100, or the last PR on a page was updated before the cutoff (`now - lookback_days`). A repo that would need more than 20 pages (2,000 PRs) fails the run, which posts nothing. The GitHub token comes from the variable named by `[github] token_env`; the Loopboard token from `[loopboard] token_env`. Neither is printed. `[github.agents]` maps a PR author login to an agent name; `[github.live_branches]` lists, per repo, base branches whose merges are live.

| PR state | Column | waiting_on |
|---|---|---|
| draft | In progress | `agent:<mapped author>` (unmapped: `human:<human>`) |
| open, any completed check-run failed (failure, timed_out, cancelled, action_required, startup_failure) | Review | `agent:<author>` (unmapped: `human:<human>`) |
| open, any check-run not completed | Review | `source:CI` |
| open, latest review of any reviewer is CHANGES_REQUESTED | Review | `agent:<author>` (unmapped: `human:<human>`) |
| open, otherwise | Review | `human:<human>` |
| merged | Review (merged, not live) | `human:<human>` |
| merged into a `live_branches` base | Done (`live_at` = `merged_at`) | `human:<human>` |
| merged elsewhere, and a `live_branches` branch contains the merge commit (D23a) | Done (`live_at` = the release PR's `merged_at`) | `human:<human>` |
| closed, not merged | Canceled | none |

Failing checks win over pending, pending over changes requested. Reviews decide only the changes-requested rule, using each reviewer's latest non-comment review. A merge into a branch not listed stays in Review until a live branch contains it or the item is marked deployed.

Releases (D23a): for each merged PR whose base is not a live branch, that has a `merge_commit_sha` and was merged within `lookback_days`, the connector asks `GET /repos/{repo}/compare/{merge_commit_sha}...{live_branch}`. A `status` of `ahead` or `identical` means the live branch contains the PR. Its `live_at` is then the `merged_at` of the earliest PR in the same listing merged into a live branch at or after the PR's own `merged_at` (the release PR, for example `development → main`), or the run time if the listing has none; `merged_at` is kept. A run makes at most 60 compare calls, oldest merged-not-live PRs first; the rest wait for a later run. A 404 or 422 from compare (for example a deleted commit) counts as not contained. Any other compare error fails the run, which posts nothing.

API budget: per repo, one listing call per page, plus check-runs and reviews (each paged at 100) only for open, non-draft PRs; drafts, merged and closed PRs need neither, since their column and `waiting_on` do not depend on checks or reviews. Add at most 60 compare calls per run. A repo with 164 PRs in the window, 8 of them open and ready, takes 2 + 8 + 8 = 18 calls; ten such repos take about 180, plus up to 60 compare calls, per 15-minute run.

Requests send `User-Agent: loopboard-connectors/<version>`, since Cloudflare's Browser Integrity Check rejects the default `Python-urllib` agent (error 1010). Titles are cut at 300 characters.

## CLI

```
loopboard sync kanban --config PATH [--board SLUG] [--cli-replay DIR] [--dry-run]
loopboard sync github --config PATH [--dry-run]
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

- `[loopboard] url`: base URL; posts go to `<url>/api/ingest`. Must be `https://`; plain `http://` is accepted only for `localhost` and `127.0.0.1` (otherwise exit 2).
- `[loopboard] token_env`: name of the environment variable holding the bearer token.
- `[general] human`: name used in `human:<human>` (for example `owner`).
- `[kanban] board`: optional Hermes board slug.
- `[kanban.tenants]`: Hermes tenant to project key (for example `demo = "DEMO"`).

`config.toml` is git-ignored; copy `connectors/config.example.toml`.
