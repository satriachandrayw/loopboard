from __future__ import annotations

import argparse
import json
import os
import sys

from . import kanban
from .client import IngestClient
from .config import load_config, resolve_token
from .contract import ConfigError, IngestRejected, SourceError


def _emit(obj: dict) -> None:
    print(json.dumps(obj))


def _sync_kanban(args, env, post, run_cli) -> int:
    try:
        cfg = load_config(args.config)
        url = cfg.get("loopboard", {}).get("url")
        if not url:
            raise ConfigError("[loopboard] url is not set")
        token = None if args.dry_run else resolve_token(cfg, env)
    except ConfigError as e:
        _emit({"connector": "kanban", "error": str(e)})
        return 2
    if run_cli is None:
        run_cli = kanban.replay_runner(args.cli_replay) if args.cli_replay else kanban.run_cli_subprocess
    kcfg = cfg.get("kanban", {})
    human = cfg.get("general", {}).get("human", "owner")
    try:
        items = kanban.collect(run_cli, human=human, tenants=kcfg.get("tenants", {}),
                               board=args.board or kcfg.get("board") or None)
    except SourceError as e:
        _emit({"connector": "kanban", "error": str(e)})
        return 1
    totals = {"accepted": 0, "created": 0, "updated": 0, "skipped_older": 0}
    posts = 0
    if items and not args.dry_run:
        client = IngestClient(url, token, post=post)
        try:
            totals = client.send("kanban", items)
        except IngestRejected as e:
            _emit({"connector": "kanban", "error": f"ingest rejected (HTTP {e.status})"})
            return 3
        posts = client.posts
    _emit({"connector": "kanban", "collected": len(items), **totals, "posts": posts,
           "dry_run": bool(args.dry_run)})
    return 0


def main(argv=None, *, env=os.environ, post=None, run_cli=None) -> int:
    p = argparse.ArgumentParser(prog="loopboard")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("sync").add_subparsers(dest="connector", required=True)
    k = sp.add_parser("kanban")
    k.add_argument("--config", required=True)
    k.add_argument("--board")
    k.add_argument("--cli-replay", metavar="DIR")
    k.add_argument("--dry-run", action="store_true")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    return _sync_kanban(args, env, post, run_cli)


if __name__ == "__main__":
    sys.exit(main())
