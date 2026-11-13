# Install and run

## Local development

Prerequisites: uv 0.13.4 or newer, Node.js with npm. Python 3.13 is fetched by uv.

```bash
bash scripts/test.sh              # worker, connector and web suites, plus the web build
bash scripts/acceptance-local.sh  # local stack check: D1, dev server, sync, HTTP checks
```

`scripts/test.sh` uses a pinned uv from `/tmp` when the installed one is older than 0.13.4.
`scripts/acceptance-local.sh` applies the migrations to a throwaway local D1, starts
`pywrangler dev` on port 8799, syncs the Kanban fixtures through the CLI, checks the board
and the 401 guard, triggers the cron handler, and prints `ACCEPTANCE PASS` only if all checks pass.
It writes nothing to the repo and keeps tokens in shell variables only.

## API tokens

```bash
cd worker
uv run python scripts/make_token.py --name reader --scopes read,write
uv run python scripts/make_token.py --name kanban-sync --scopes ingest --source kanban
uv run python scripts/make_token.py --name owner-cli --scopes read,write,human
```

Add `human` to a person's own token: Loopboard then treats its writes as a human's (only a human
confirms a task done). Agent tokens never carry it.

The script prints `TOKEN=lb_...` once, then an `INSERT` statement holding only the token's
sha256. Run the INSERT against D1 (for example
`npx wrangler d1 execute loopboard --local --command "<INSERT ...>"`). Store the token somewhere
safe; it cannot be shown again. A token bound to a `source` can ingest only for that source.

## Cloudflare Access

Set the Worker vars `ACCESS_TEAM_DOMAIN` (`<your-team>.cloudflareaccess.com`) and `ACCESS_AUD`
(the Access application's audience tag).

- Both unset (the default): Access is off; only bearer tokens authenticate.
- Both set: a request carrying a valid `Cf-Access-Jwt-Assertion` (RS256, verified against the
  team certs, audience `ACCESS_AUD`) is accepted as that user with all scopes. A bare
  `Cf-Access-Authenticated-User-Email` header is ignored, because workers.dev accepts any header.
- Access service-token JWTs carry no `email` claim and are rejected (401). Machines use
  Loopboard bearer tokens instead.
- Bearer tokens keep working either way, so connectors do not need Access.

## Connectors

Create every project first (`POST /api/projects`, see [api.md](api.md)): ingest rejects an
unknown `project_key` with 422, so a sync whose tenants or repos map to a missing project posts
nothing. Then copy `connectors/config.example.toml` to `connectors/config.toml` (git-ignored), set
the Loopboard URL, tenant and repo mappings, and export the token named by `token_env`. Then run
`uv run loopboard sync kanban --config connectors/config.toml`. See
[connectors.md](connectors.md) for the contract and mappings, and [api.md](api.md) for the API.

## Rollout (not part of the v1a build)

None of these steps is done by the v1a build. Each needs the owner's OK first.

1. First deploy: create the D1 database, put its id in `worker/wrangler.jsonc`, apply the
   migrations remotely, deploy the Worker. Free-plan CPU time and D1 queries per invocation are
   unmeasured so far (ingest is bounded to about 10 D1 calls per 100-item request); check the
   Worker's CPU time and D1 metrics after the first real syncs.
2. DNS: point a custom hostname at the Worker, if one is wanted instead of workers.dev.
3. Access application: create a Cloudflare Access application for the hostname, then set
   `ACCESS_TEAM_DOMAIN` and `ACCESS_AUD`.
4. Hermes crons: schedule `loopboard sync kanban` and `loopboard sync github` on the machine
   that holds the source tokens.
5. Hermes skill changes: let agents create and update epics through the write API.
