from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from . import asks, github, kanban
from .client import COUNTS, IngestClient
from .config import check_url, load_config, resolve_token
from .contract import ConfigError, IngestRejected, SourceError


def _emit(obj: dict) -> None:
    print(json.dumps(obj))


def _sync_kanban(args, env, post, run_cli) -> int:
    try:
        cfg = load_config(args.config)
        url = cfg.get("loopboard", {}).get("url")
        if not url:
            raise ConfigError("[loopboard] url is not set")
        check_url(url)
        token = None if args.dry_run else resolve_token(cfg, env)
    except ConfigError as e:
        _emit({"connector": "kanban", "error": str(e)})
        return 2
    if run_cli is None:
        if args.cli_replay:
            run_cli = kanban.replay_runner(args.cli_replay)
        else:
            # Every configured token var, plus GITHUB_TOKEN as the [github] default when unset.
            names = {cfg.get("loopboard", {}).get("token_env"),
                     cfg.get("github", {}).get("token_env") or "GITHUB_TOKEN"}
            exclude = tuple(n for n in names if n)
            run_cli = lambda argv: kanban.run_cli_subprocess(argv, exclude=exclude)  # noqa: E731
    kcfg = cfg.get("kanban", {})
    human = cfg.get("general", {}).get("human", "owner")
    try:
        items = kanban.collect(run_cli, human=human, tenants=kcfg.get("tenants", {}),
                               board=args.board or kcfg.get("board") or None)
    except SourceError as e:
        _emit({"connector": "kanban", "error": str(e)})
        return 1
    totals = {k: 0 for k in COUNTS}
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


def _scrub(msg: str, *secrets) -> str:
    for s in secrets:
        if s:
            msg = msg.replace(s, "***")
    return msg


def _sync_github(args, env, post, fetch_json, now) -> int:
    try:
        cfg = load_config(args.config)
        url = cfg.get("loopboard", {}).get("url")
        if not url:
            raise ConfigError("[loopboard] url is not set")
        check_url(url)
        token = None if args.dry_run else resolve_token(cfg, env)
        gcfg = cfg.get("github", {})
        gname = gcfg.get("token_env")
        if not gname:
            raise ConfigError("[github] token_env is not configured")
        gtoken = env.get(gname)
        if not gtoken:
            raise ConfigError("GitHub token environment variable is not set")
        repos = gcfg.get("repos", {})
        if not repos:
            raise ConfigError("[github.repos] is empty")
        agents = gcfg.get("agents", {})
        live = gcfg.get("live_branches", {})
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in repos.items()):
            raise ConfigError("[github.repos] values must be strings")
        if not all(isinstance(v, str) for v in agents.values()):
            raise ConfigError("[github.agents] values must be strings")
        if not all(isinstance(v, list) and all(isinstance(b, str) for b in v) for v in live.values()):
            raise ConfigError("[github.live_branches] values must be lists of strings")
        lookback = gcfg.get("lookback_days", 14)
        if not isinstance(lookback, int) or isinstance(lookback, bool) or lookback < 1:
            raise ConfigError("[github] lookback_days must be a positive integer")
    except ConfigError as e:
        _emit({"connector": "github", "error": str(e)})
        return 2
    if fetch_json is None:
        fetch_json = github.default_fetch_json(gtoken)
    human = cfg.get("general", {}).get("human", "owner")
    try:
        items = github.collect(fetch_json, repos=repos, human=human, agent_logins=agents,
                               live_branches=live, lookback_days=lookback,
                               now=int(time.time()) if now is None else now)
    except SourceError as e:
        _emit({"connector": "github", "error": _scrub(str(e), token, gtoken)})
        return 1
    totals = {k: 0 for k in COUNTS}
    posts = 0
    if items and not args.dry_run:
        client = IngestClient(url, token, post=post)
        try:
            totals = client.send("github", items)
        except IngestRejected as e:
            _emit({"connector": "github", "error": f"ingest rejected (HTTP {e.status})"})
            return 3
        posts = client.posts
    _emit({"connector": "github", "collected": len(items), **totals, "posts": posts,
           "dry_run": bool(args.dry_run)})
    return 0


_SOURCE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
_PROJECT = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")


def _asks_config(cfg: dict, config_path) -> tuple[Path, str, dict, str]:
    acfg = cfg.get("asks", {})
    file = acfg.get("file")
    if not isinstance(file, str) or not file:
        raise ConfigError("[asks] file is not set")
    path = Path(file).expanduser()
    if not path.is_absolute():
        path = Path(config_path).parent / path
    source = acfg.get("source", "asks")
    if not isinstance(source, str) or not _SOURCE.match(source):
        raise ConfigError("[asks] source must look like a source name (lowercase, 2-32 chars)")
    default = acfg.get("default_project")
    if not isinstance(default, str) or not _PROJECT.match(default):
        raise ConfigError("[asks] default_project must be a project key")
    projects = acfg.get("projects", {})
    if not isinstance(projects, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and _PROJECT.match(v) for k, v in projects.items()):
        raise ConfigError("[asks.projects] values must be project keys")
    return path, source, projects, default


def _sync_asks(args, env, post) -> int:
    try:
        cfg = load_config(args.config)
        url = cfg.get("loopboard", {}).get("url")
        if not url:
            raise ConfigError("[loopboard] url is not set")
        check_url(url)
        token = None if args.dry_run else resolve_token(cfg, env)
        path, source, projects, default = _asks_config(cfg, args.config)
    except ConfigError as e:
        _emit({"connector": "asks", "error": str(e)})
        return 2
    human = cfg.get("general", {}).get("human", "owner")
    try:
        items = asks.collect(path, source=source, human=human, projects=projects, default_project=default)
    except SourceError as e:
        _emit({"connector": "asks", "error": str(e)})
        return 1
    totals = {k: 0 for k in COUNTS}
    posts = 0
    if items and not args.dry_run:
        client = IngestClient(url, token, post=post)
        try:
            totals = client.send(source, items)
        except IngestRejected as e:
            _emit({"connector": "asks", "error": f"ingest rejected (HTTP {e.status})"})
            return 3
        posts = client.posts
    _emit({"connector": "asks", "collected": len(items), **totals, "posts": posts,
           "dry_run": bool(args.dry_run)})
    return 0


def main(argv=None, *, env=os.environ, post=None, run_cli=None, fetch_json=None, now=None) -> int:
    p = argparse.ArgumentParser(prog="loopboard")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("sync").add_subparsers(dest="connector", required=True)
    k = sp.add_parser("kanban")
    k.add_argument("--config", required=True)
    k.add_argument("--board")
    k.add_argument("--cli-replay", metavar="DIR")
    k.add_argument("--dry-run", action="store_true")
    g = sp.add_parser("github")
    g.add_argument("--config", required=True)
    g.add_argument("--dry-run", action="store_true")
    a = sp.add_parser("asks")
    a.add_argument("--config", required=True)
    a.add_argument("--dry-run", action="store_true")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    if args.connector == "asks":
        return _sync_asks(args, env, post)
    if args.connector == "github":
        return _sync_github(args, env, post, fetch_json, now)
    return _sync_kanban(args, env, post, run_cli)


if __name__ == "__main__":
    sys.exit(main())
