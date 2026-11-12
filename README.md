# Loopboard

A small, open-source project tracker for work that AI agents do.

Loopboard groups work from agent tools (Hermes Kanban cards, GitHub pull requests, and later chat sessions and Paperclip issues) into **Projects → Epics → Tasks** on a five-column board (Backlog, Todo, In progress, Review, Done). It shows who every card is waiting on, an agent or you, and flags work that has stalled, so nothing gets stranded.

- Runs as one Cloudflare Worker: Python (FastAPI) + D1, with a React frontend.
- Connectors run on your own machine and push to Loopboard's ingest API, so your source tokens never leave it.
- Read-only towards your tools in v1: it tracks, it doesn't act.

**Status:** pre-alpha, v1a under construction. See [`docs/design.md`](docs/design.md) and the [v1a plan](docs/plans/2026-11-12-loopboard-v1a.md).

## Filing work to an epic

Synced cards and pull requests land in **Unfiled**. To file one under an epic, start its title
with the epic key in brackets, for example a Kanban card or PR titled
`[DEMO-E5] Add checkout retry`. The next sync files it under `DEMO-E5` and stores the title as
`Add checkout retry`. The tag only files new or still-unfiled items; a filing made by a person or
Hermes is never changed by it. An unknown key leaves the item in Unfiled and is counted as
`unknown_epic` in the sync summary. See [Connectors](docs/connectors.md#filing-by-title-prefix).

## Docs

- [Install and run](docs/install.md)
- [API](docs/api.md)
- [Connectors](docs/connectors.md)
- [Design](docs/design.md)

## License

MIT
