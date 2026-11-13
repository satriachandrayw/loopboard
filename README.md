# Loopboard

A small, open-source project tracker for work that AI agents do.

Loopboard groups work from agent tools (Hermes Kanban cards, GitHub pull requests, and later chat sessions and Paperclip issues) into **Projects → Epics → Tasks** on a five-column board (Backlog, Todo, In progress, Review, Done). It shows who every card is waiting on, an agent or you, and flags work that has stalled, so nothing gets stranded.

- Runs as one Cloudflare Worker: Python (FastAPI) + D1, with a React frontend.
- Connectors run on your own machine and push to Loopboard's ingest API, so your source tokens never leave it.
- Read-only towards your tools in v1: it tracks, it doesn't act.

**Status:** pre-alpha, v1a under construction. See [`docs/design.md`](docs/design.md) and the [v1a plan](docs/plans/2026-11-12-loopboard-v1a.md).

## Tasks

- A task has its own key per project, `DEMO-12`, next to epic keys like `DEMO-E5`; it belongs to at most one epic, and a task without one sits in the **No epic** lane of the Tasks board (Board → Epics | Tasks).
- Start a Kanban card or PR title with `[DEMO-12]` and the next sync links it to that task; a title tagged only `[DEMO-E5]` gets a new task made for it under that epic. Untagged items land in **Unfiled**, where you link them to a task, make a task from them, or ignore them.
- A task's **refs** are other keys that mean it (say another tracker's `OPS-8001`): a title carrying a ref as a whole word links too, within the same project only. Tags never move an item a person already filed, and unknown keys never fail a sync.
- Status follows the links: any linked item running → In progress, any in review → Review, all done (merged PRs once live) → Done. A task without links moves by hand, and an agent's Done waits for a human to confirm it.
- An epic's column and progress (done tasks / tasks) come from its tasks. See [Connectors](docs/connectors.md#linking-by-title-prefix-and-refs) and the [tasks design](docs/design-tasks.md).

## Docs

- [Install and run](docs/install.md)
- [API](docs/api.md)
- [Connectors](docs/connectors.md)
- [Design](docs/design.md)

## License

MIT
