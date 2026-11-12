# Loopboard - Design

> Public design for Loopboard v1. Approved 2026-11-12.

## Intent

The owner runs many pieces of work at once through agents: Hermes chat threads, Hermes Kanban cards, Paperclip companies and GitHub PRs. Nothing shows them in one place. The list lives in the owner's head, split across chat threads, and when an item is forgotten it is stranded. Often the stranded item is waiting on the owner, or on an agent that said "I'll continue once CI is green" with nothing scheduled to wake it.

Loopboard is a small project tracker for agent-run work, in the style of Jira or Linear. It groups work into **Projects → Epics → Tasks**. Each task links to the place where the work actually runs. Loopboard keeps the status current from those sources and flags what has stalled, so nothing waits on the owner without them knowing, and nothing waits on an agent forever.

It is built for the owner's setup first and published as open source under `satriachandrayw/loopboard`. It is designed so other people running agents (Hermes, Paperclip or anything else) could use it too.

**Success:**
- Every piece of in-flight work the owner has started shows up on the board within an hour, filed under an epic or visible in the Unfiled inbox.
- The owner and their chat assistant can answer "what is waiting on me?" and "what has stalled?" from one screen.
- A stall on an agent gets driven forward by a Hermes cron without the owner remembering it.

## Goals

- One list of all work in flight across projects, with a calculated status and who it is waiting on.
- Epics as SDLC-staged containers (Idea → Spec → Plan → Build → Review → Ship → Done) with calculated progress.
- An **Unfiled inbox**: every item a connector finds that is not linked to an epic lands there, so nothing disappears unseen.
- Stall detection from source activity.
- A clean public API, so agents keep the board current and any tool can push items.
- Connectors as plugins with declared abilities; Hermes and Paperclip are connectors, not the core.

## Non-goals / anti-goals

- **v1 does not create or invoke work.** It only tracks. Driving stalled agents is done by a Hermes cron that reads Loopboard's API. Creating work from an epic through Hermes is v2.
- Not a replacement for Hermes Kanban or Paperclip. Each source stays the truth for its own execution state; Loopboard owns only grouping and intent.
- No sprints, story points, time tracking, Gantt, roadmaps, custom fields or team permissions in v1.
- **Anti-goals:**
  - Loopboard writing to Paperclip, or reading Paperclip routes that have side effects.
  - Secrets, customer data or message bodies stored in Loopboard.
  - Anything private to the owner's setup (chat thread ids, the chat assistant, project names, private note paths) in the public repo.
  - A board so noisy (hundreds of Paperclip chores a day) that nobody looks at it.

## Approaches considered

**Where the tracker lives**
- **Linear / Plane Cloud.** Ready-made UI. Rejected: the owner wants an epic inside a project (Linear makes the initiative a project), data with a third party, and a plan limit or paywall (Linear Free caps at 250 issues; Plane Free has no epic type).
- **Self-hosted Plane Community.** Rejected: about 4 GB of RAM on the owner's server that should go to agent work, plus another stack to keep upgraded.
- **Hermes dashboard plugin**. Rejected: ties the product to Hermes. The owner wants a standalone app with Hermes and Paperclip as connectors.
- **Standalone app (chosen).**

**How the standalone app is built**
- TypeScript service + SQLite on a home machine. Close to Hermes, but uses local resources and depends on the host.
- **Cloudflare Worker: Python (FastAPI) backend + D1 + React frontend (chosen).** Zero resources on the owner's machines, their production stack, free tier. Self-hosters need a Cloudflare account; keeping the database layer thin leaves room for a plain-server version later.
- Python with server-rendered pages. Rejected: a Linear-feel UI is harder without a real frontend.

**How work gets into epics**
- By hand only: depends on the owner remembering, which is today's problem.
- Agents file it through the API: automatic, but anything an agent forgets slips.
- **Agents file it, plus an Unfiled inbox (chosen):** nothing can disappear without being seen; humans sort only the leftovers.

## Spike result (2026-11-12, local only)

One Python Worker ran FastAPI, D1, a cron trigger and a React (Vite) build together under `pywrangler dev`:
- API routes read and write D1; a warm request took about 25 ms locally.
- An ingest endpoint upserted Kanban cards by `(source, external_id)` without duplicates.
- A "no activity for 2 days" query returned exactly the backdated item.
- The cron trigger fired a `scheduled` method on the same class as the FastAPI app and fetched live GitHub PRs.
- `/api/*` went to FastAPI and every other path to the React app, so deep links work.

Learned: `pywrangler` needs uv 0.13.4 or newer; the bundled Python packages are about 9.5 MB. Not yet measured: cold start on Cloudflare and D1 free-tier usage.

## Chosen design

### Building blocks

- **Project:** a product (for example, `<PROJECT>`). Has a short key (`DEMO`).
- **Epic:** a goal inside one project. Fields:
  - `key` (`DEMO-E14`), title, one-paragraph goal;
  - `column`: backlog, todo, in_progress, review, done (plus canceled, hidden from the board), and a finer `stage` label: idea, spec, plan, build, review, ship (see Workflow below);
  - `owner` (an agent or a human), `next_step` (one line), `waiting_on`;
  - `home` link (the thread or doc where it is steered);
  - links to its spec/plan.
  - **Progress is calculated** from its tasks, never typed.
- **Task (item):** one piece of work in a source system. Fields:
  - `source` + `external_id` (unique together) and a link back to the source;
  - title, `status_category`: backlog, todo, in_progress, blocked, review, done, canceled, plus the source's raw status;
  - `owner`, `waiting_on`, `next_step`, `last_activity_at`;
  - `filing`: unfiled, epic (with the epic id), standalone (belongs to a project but no epic; recurring or small work), or ignored.
- **Waiting on** is a first-class field: `agent:<name>`, `human:<name>`, or `source:<system>` (for example "CI"). No mainstream PM tool has it; it is the reason this exists.
- **Relations:** `blocks / blocked by` between tasks and epics.
- **Activity log:** append-only events (who, what, when, from which connector or API token). Current state is a projection of the log. Every change by an agent or a human is visible.

### Rules taken from mature PM tools

1. Calculate fields rather than asking for them: progress, last activity and stalled are computed.
2. One owner per item.
3. API first: the UI and the agents use the same API, and agents are named actors in the activity log.
4. The source is the truth for execution state; Loopboard stores a link, a title, a status and who it waits on, never the details.
5. People are pinged only for what needs them.

### Workflow: five columns (the owner's call, refined by a PM council, 2026-11-12)

The owner found one column per stage too much and proposed five. A four-seat council (flow design, solo-founder focus, automation, red team) kept those five columns and added the rules that stop it hiding stranded work.

| Column | Means | How a card gets there |
|---|---|---|
| Backlog | Parked idea. Nothing is committed and no agent starts from here. | Captured by an agent or the owner. |
| Todo | The owner said go. Spec and plan get written and approved here. | Manual: the owner's "go" is the only drag on the board. |
| In progress | Agents are building. | Automatic: any task running. |
| Review | Handed over for review, merge and deploy. | Automatic: no task running and at least one in review, or code merged but not live. |
| Done | Live, not just merged. | Automatic: all tasks done and deploy evidence present. Epics without code are confirmed by a human. Hidden after 7 days, never deleted. |

Rules:
- **The stage label keeps the detail** (idea, spec, plan, build, review, ship), set by agents through the API. It replaces the extra columns.
- **Waiting on is required on every card.** Todo cards waiting on a spec or plan approval show "awaiting your approval" and appear in Needs you.
- **Blocked and stalled are flags, not columns.** A blocked task flags its epic without moving it. A task marked running with no heartbeat past the threshold gets a stale flag and a driver nudge; it never moves the column.
- **Merged but not live** stays in Review with a "merged, not live" flag and appears in Needs you until deploy evidence arrives.
- **Review is the owner's bottleneck:** the column header warns past 3 cards (a warning, not a block). Review split by owner: "review · agent" stays out of Needs you, "review · you" goes into it.
- **Source status mapping:**
  - Hermes Kanban: triage, todo, ready → Todo; running → In progress; review → Review; done → Done; blocked → flag.
  - Paperclip: backlog → Backlog; todo → Todo; in_progress → In progress; in_review → Review; done → Done; blocked → flag; cancelled → ignored.
  - GitHub PR: draft → In progress; open → Review; merged → Review with "merged, not live" until deployed; closed unmerged → ignored.
  - Hermes chat thread: active → In progress; waiting on the owner → flag plus Needs you; finished → Review until the owner or the agent confirms.

### Stalled

An item or epic is **stalled** when it is not done or canceled and its `last_activity_at` is older than a threshold. The threshold is configurable per source, with a default of 24 hours.
- Stalled and waiting on an agent: listed for the Hermes driver cron.
- Stalled and waiting on a human: listed for the nudge.
- An epic is stalled when none of its open tasks has moved within the threshold, or when it has no open tasks and is not in Done. This applies in Todo too, so a spec waiting on approval can't sit unseen.

### Connectors

All connectors follow one contract. A connector:
- finds and fetches its items;
- maps each item's status onto the shared categories and sets `waiting_on`;
- reports `last_activity_at`;
- declares its abilities: read, comment, drive (v1 connectors are read-only).

**Every v1 connector runs as a push connector** in a small Python runner (`loopboard sync <connector>`) next to the source, posting to the ingest API with a bearer token. The owner's runner is a Hermes cron. *Builder's note, Hermes's call:* the spike proved pull connectors inside the Worker work, but running them on the host keeps the Paperclip board key and GitHub token off Cloudflare. The Worker's cron trigger is still used for stall computation.

v1 connectors:
- **Hermes Kanban:** reads `hermes kanban list/show --json` on the host. Card status maps directly; `blocked` with a needs-input reason means waiting on a human.
- **GitHub PRs:** open PRs in configured repos; a PR waiting for review or merge approval is waiting on a human, failing CI is waiting on its author agent.
- **Hermes chat sessions:** the source of most stranded work. The connector looks at sessions with new messages since its last run and asks a small model to classify each one as done, waiting on the owner, waiting on an agent, or idle, with a one-line next step. Where the chat assistant ledger already has an open item for that session, that wins as "waiting on the owner". Only the session title, the classification and the next-step line leave the host; message text never does, and the line is scrubbed for secret shapes.
- **Paperclip (read-only):** uses only the routes proven side-effect-free in the Paperclip read contract (the company activity feed, issue activity, comments, agents, approvals). It never calls the issue-detail or issue-list routes, because those can cancel recovery actions. Paperclip produces a high volume of routine done issues, mostly content chores, so it does **not** pull every issue. It tracks:
  - pending board approvals (waiting on the owner);
  - issues explicitly linked to an epic through the API;
  - issues that turn blocked.
- **Drive for Paperclip is off by default**, matching the owner's rule that Paperclip issues are only commented on or woken at the owner's request.

### The Hermes-side crons (the owner's setup, private config)

- **Sync** (hourly, no agent): runs the Kanban, GitHub and Paperclip connectors.
- **Session classifier** (hourly, agent): runs the chat-session connector.
- **Driver** (hourly): reads `GET /api/stalled?waiting_on=agent`.
  - A stalled Kanban card is unblocked or re-dispatched only when its block is not a human question.
  - A stalled chat session is continued through the chat assistant's existing injection path, within the chat assistant's loop limits, and only for a next step that was already approved.
  - Anything high-risk (merge to main, deploy, DNS, restarts, destructive, cost, messaging a human) is never driven; it turns into a "waiting on the owner" item.
- **Nudge and digest:** "waiting on the owner" items stalled past the threshold are posted to the chat assistant thread, plus one daily digest. The digest lists Unfiled items with `L-` codes. The owner or the chat assistant reply `L-3 → DEMO-E14`, `L-3 standalone` or `L-3 ignore`, and the agent applies it through the API.

### Epics stay current without the owner

- When the owner approves a spec or plan in a thread, Hermes creates or advances the epic through the API (a rule in the relevant Hermes skills).
- When Hermes creates a Kanban card or PR for an epic, it links it at creation.
- The column follows the tasks by itself (Workflow below); agents write task status and the stage label, never the column.

### Screens (mobile-first; approved mockups, not included)

The approved mockups (not included) show each screen. Screen 3 (the Epics list) in the first mockup set is replaced by the board view further down.

1. **Needs you:** everything waiting on the signed-in human, oldest first.
2. **Stalled:** everything stalled, grouped by who it waits on.
3. **Board (the main view):** a Kanban board of epics in the five columns below. Each card shows four things: who it waits on and for how long (orange name = the owner, teal = an agent, red edge when stalled), the stage label, progress (`3/4`) and the project tag. Flags such as "awaiting your approval", "blocked: needs your input" and "merged, not live" sit under the card. Filters for project and "waiting on". On a phone it shows one column at a time.
4. **Epic detail:** goal, stage, next step, its tasks as a board by status category (Todo, In progress, Blocked, Review, Done), and the activity log. Task cards can't be dragged: their status comes from the source, so a task card opens the source instead.
5. **Unfiled:** the inbox, with one-tap filing to an epic, standalone or ignore.

Needs you, Stalled and Unfiled stay lists, because they are queues to clear oldest-first, not workflows.

An earlier 7-column version (one column per stage) was rejected as too much.

### Security

- Every `/api` route needs either a Cloudflare Access identity or a bearer token. No anonymous mode.
- Connector tokens are per connector and can only ingest. UI writes (filing, editing epics) need the Access identity or a token with write scope.
- The owner's deployment sits behind Cloudflare Access on its own hostname.

### Repo layout and stack

One public monorepo, `satriachandrayw/loopboard`:
- `worker/`: Python FastAPI on Cloudflare Workers with D1. Pins uv 0.13.4 or newer. Database code is kept in one thin layer.
- `web/`: React + TypeScript (Vite), served as static assets by the same Worker.
- `connectors/`: the Python runner and the Hermes Kanban, Hermes sessions, GitHub and Paperclip connectors.
- `docs/`: install, the connector contract, the API.

The owner's own config (thread ids, chat assistant hooks, project list, cron definitions) stays outside the repo, in a private repo or under the Hermes home.

**Left to the builder:** the exact table schema, migrations tooling, how the web app fetches data, test layout (pytest against local D1, Vitest for the web), and CI on GitHub Actions.

### Rollout steps that need the owner's OK

1. Creating the public GitHub repo (publishing).
2. The first Cloudflare deploy, the hostname's DNS record and the Access application.
3. The Hermes crons (sync, classifier, driver, digest).
4. Changing Hermes skills so agents create and update epics.

### Phases

- **v1a:** core model, ingest API, stall computation, the five screens, Hermes Kanban and GitHub connectors.
- **v1b:** Hermes chat-session connector, Paperclip connector, driver, nudge and digest with `L-` codes.
- **v2:** invoke work through Hermes: create a card or session from an epic.

## Settled after the builder check (2026-11-12)

Answered from the existing setup:
- **Chat assistant ledger:** a local SQLite file in the Hermes home, table `items` (one row per point where a session waited on the owner, with `status`, `lane` and `session_key`). The chat assistant is in `shadow` mode, so rows are recorded but nothing is injected. The session connector reads it read-only.
- **Paperclip read contract:** done on 2026-11-06 and kept with the owner's tooling. "Issue turned blocked" comes from `issue.updated` activity rows whose `details.status` changes to blocked; no issue-list or issue-detail route is needed. The activity feed has no "since" parameter, so the connector polls hourly and stops at the last-seen activity id.
- **`L-` replies:** the chat assistant's plugin only claims its own short reply codes; any other message in its thread, like other short reply codes today, reaches the agent as a normal turn. `L-` codes take the same path, and the agent applies them through the API. No plugin change is needed.

Hermes's calls (minor; a sensible builder could make them):
- **Reading sessions:** the same read-only `state.db` lookup the chat assistant uses, with the same rule that it switches itself off if Hermes changes its session tables.
- **Classifier model and budget:** Haiku through the existing Claude subscription, with its own cap of 100 calls a day, separate from the chat assistant's 300. It classifies only sessions with new messages since its last run.
- **Gate before the driver touches chat sessions:** one shadow week in which the classifier runs but nothing is driven. The owner labels about 30 sessions. The driver is enabled only if at least 90% of the sessions marked "waiting on an agent" really were.
- **Which Kanban blocks are driveable:** only `transient` blocks (re-dispatch once). `dependency` blocks resolve by themselves. `needs_input` and `capability` blocks and anything in `review` are waiting on the owner and are never driven.
- **High-risk check:** the driver reuses the chat assistant's deterministic policy check (merge or push to main or production, deploy, DNS, restarts, destructive operations), not the classifier's judgement.
- **Auth for self-hosters:** both are supported. A Cloudflare Access identity, or bearer tokens with scopes (`ingest`, `read`, `write`). Without Access, the web app asks for a token once and keeps it in the browser.

The owner's decisions on the builder check (2026-11-12):
- **What the driver may continue in a chat thread:** any next step the agent itself stated, unless the chat assistant's deterministic policy check flags it high-risk. The driver's message is "continue with what you said you'd do next; ask the owner if it needs their decision", so the agent's own approval rules still apply.
- **The chat assistant is in shadow mode:** driving chat threads waits for the chat assistant to go live, and the owner asked to start the chat assistant go-live now. Until then, a chat thread stalled on an agent becomes a nudge to the owner. Kanban cards are driven from day one.

## Risks and open questions

- **Session classification is the weakest link.** A wrong "done" hides a stranded item; a wrong "waiting on agent" makes the driver poke a finished thread. Mitigation: low-confidence results default to "waiting on the owner", the shadow-week accuracy gate, and the chat assistant's high-risk policy check on every driven step.
- **The driver overlaps the chat assistant's non-goal "starting new work".** It continues agent-stated next steps (never high-risk ones), which changes what the chat assistant does, and the chat assistant is still in shadow mode.
- **Noise.** If the Unfiled inbox grows faster than it is sorted, the board loses trust. Watch the inbox size in the first two weeks.
- **Python Workers maturity.** The package bundle is large and the Python tooling moves fast; a breaking change could stall deploys.
- **Name.** A VS Code extension named LoopBoard exists; low confusion risk.
