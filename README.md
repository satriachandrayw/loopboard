# Loopboard

A small, open-source project tracker for work that AI agents do.

Loopboard groups work from agent tools (Hermes Kanban cards, GitHub pull requests, and later chat sessions and Paperclip issues) into **Projects → Epics → Tasks** on a five-column board (Backlog, Todo, In progress, Review, Done). It shows who every card is waiting on, an agent or you, and flags work that has stalled, so nothing gets stranded.

- Runs as one Cloudflare Worker: Python (FastAPI) + D1, with a React frontend.
- Connectors run on your own machine and push to Loopboard's ingest API, so your source tokens never leave it.
- Read-only towards your tools in v1: it tracks, it doesn't act.

**Status:** pre-alpha, v1a under construction. See [`docs/design.md`](docs/design.md) and the [v1a plan](docs/plans/2026-11-12-loopboard-v1a.md).

## License

MIT
