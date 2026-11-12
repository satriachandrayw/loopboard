"""Hermes Kanban connector (read-only). Free text (body, result, summaries,
comments, payload.reason) is never read."""
from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .contract import Item, SourceError

CATEGORY = {
    "triage": "todo", "todo": "todo", "ready": "todo", "running": "in_progress",
    "review": "review", "blocked": "blocked", "done": "done", "archived": "canceled",
}


_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _iso(epoch) -> str:
    return datetime.fromtimestamp(int(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _need(d: dict, key: str):
    if not isinstance(d, dict) or key not in d:
        raise SourceError(f"missing field: {key}")
    return d[key]


def _block_kind(events: list) -> str:
    newest = None
    for e in events:
        if e.get("kind") == "blocked" and (newest is None or e["created_at"] >= newest["created_at"]):
            newest = e
    payload = (newest or {}).get("payload") or {}
    return "needs_input" if payload.get("kind") == "needs_input" else "other"


def map_task(task: dict, show: dict, *, human: str, tenants: dict[str, str]) -> Item:
    status = _need(task, "status")
    if status not in CATEGORY:
        raise SourceError(f"unknown status: {status}")
    category = CATEGORY[status]
    assignee = task.get("assignee")
    agent = f"agent:{assignee}" if isinstance(assignee, str) and _NAME.fullmatch(assignee) else None
    events = _need(show, "events")
    reason = None
    if status in ("triage", "review"):
        waiting = f"human:{human}"
    elif status in ("todo", "ready"):
        waiting = agent or "source:kanban"
    elif status == "running":
        waiting = agent or "source:kanban"
    elif status == "blocked":
        reason = _block_kind(events)
        waiting = f"human:{human}" if reason == "needs_input" else "source:kanban"
    else:
        waiting = None
    stamps = [task.get(k) for k in ("created_at", "started_at", "completed_at")]
    stamps = [s for s in stamps if s is not None]
    stamps += [e["created_at"] for e in events]
    if not stamps:
        raise SourceError("no timestamps")
    return Item(
        source="kanban", external_id=str(_need(task, "id")), title=str(_need(task, "title"))[:300], url=None,
        status_category=category, raw_status=status,
        owner=agent, waiting_on=waiting, blocked_reason=reason, next_step=None,
        project_key=tenants.get(task.get("tenant")), epic_key=None,
        last_activity_at=_iso(max(stamps)),
    )


def _parse(text: str):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        raise SourceError("unparseable hermes output") from None


def collect(run_cli: Callable[[list[str]], str], *, human: str, tenants: dict[str, str],
            board: str | None) -> list[Item]:
    base = ["hermes", "kanban"] + (["--board", board] if board else [])
    tasks = _parse(run_cli(base + ["list", "--json"]))
    if not isinstance(tasks, list):
        raise SourceError("unexpected list shape")
    items = []
    for t in tasks:
        tid = _need(t, "id")
        show = _parse(run_cli(base + ["show", str(tid), "--json"]))
        try:
            items.append(map_task(t, show, human=human, tenants=tenants))
        except SourceError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError):
            raise SourceError(f"malformed data for task {tid}") from None
    return items


def _child_env(exclude=()) -> dict[str, str]:
    """Minimal environment for the hermes child: never Loopboard or GitHub tokens, including
    the configured token variables even when their names start with HERMES_."""
    return {k: v for k, v in os.environ.items()
            if (k in ("PATH", "HOME", "LANG") or k.startswith("HERMES_")) and k not in exclude}


def run_cli_subprocess(argv: list[str], *, exclude=()) -> str:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=120, env=_child_env(exclude))
    except (OSError, subprocess.SubprocessError) as e:
        raise SourceError(f"cannot run {argv[0]}") from None
    if p.returncode != 0:
        raise SourceError(f"{argv[0]} exited {p.returncode}")
    return p.stdout


def replay_runner(directory) -> Callable[[list[str]], str]:
    d = Path(directory)

    def run(argv: list[str]) -> str:
        i = 4 if argv[2:3] == ["--board"] else 2
        cmd = argv[i:i + 1]
        if cmd == ["show"] and len(argv) > i + 1:
            name = f"show-{argv[i + 1]}.json"
        elif cmd == ["list"]:
            name = "list.json"
        else:
            raise SourceError("unsupported command")
        try:
            return (d / name).read_text()
        except OSError:
            raise SourceError(f"missing replay file {name}") from None

    return run
