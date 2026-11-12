"""GitHub pull request connector (read-only). Mapping rules: D19, D23, R10."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .contract import Item, SourceError

API = "https://api.github.com"
TITLE_MAX = 300
FAILING = {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}


def _runs(checks) -> list[dict]:
    if isinstance(checks, dict):
        checks = checks.get("check_runs", [])
    return list(checks or [])


def _changes_requested(reviews) -> bool:
    latest: dict[str, tuple[str, str]] = {}
    for r in sorted(reviews or [], key=lambda r: r.get("submitted_at") or ""):
        state = r.get("state")
        if state in ("COMMENTED", "PENDING"):
            continue
        who = (r.get("user") or {}).get("login")
        latest[who] = (state, r.get("submitted_at") or "")
    return any(s == "CHANGES_REQUESTED" for s, _ in latest.values())


def map_pr(pr: dict, *, checks, reviews, project_key, human, agent_logins: dict[str, str],
           live_branches: list[str]) -> Item:
    repo_number = f"{pr['number']}"
    login = (pr.get("user") or {}).get("login")
    agent = agent_logins.get(login)
    agent_tag = f"agent:{agent}" if agent else None
    human_tag = f"human:{human}"
    merged_at = pr.get("merged_at")
    live_at = None
    if pr.get("state") == "closed" and merged_at:
        raw, cat, waiting = "merged", "review", human_tag
        if (pr.get("base") or {}).get("ref") in live_branches:
            live_at = merged_at
    elif pr.get("state") == "closed":
        raw, cat, waiting = "closed", "canceled", None
    elif pr.get("draft"):
        raw, cat, waiting = "draft", "in_progress", agent_tag or human_tag
    else:
        raw, cat = "open", "review"
        runs = _runs(checks)
        if any(r.get("status") == "completed" and r.get("conclusion") in FAILING for r in runs):
            waiting = agent_tag or human_tag
        elif any(r.get("status") != "completed" for r in runs):
            waiting = "source:CI"
        elif _changes_requested(reviews):
            waiting = agent_tag or human_tag
        else:
            waiting = human_tag
    html = pr.get("html_url") or ""
    repo = pr.get("_repo") or _repo_from_url(html)
    return Item(source="github", external_id=f"{repo}#{repo_number}",
                title=(pr.get("title") or "")[:TITLE_MAX], url=html or None,
                status_category=cat, raw_status=raw, owner=agent_tag, waiting_on=waiting,
                blocked_reason=None, next_step=None, project_key=project_key, epic_key=None,
                last_activity_at=pr["updated_at"], merged_at=merged_at, live_at=live_at)


def _repo_from_url(html: str) -> str:
    parts = html.split("github.com/", 1)[-1].split("/")
    return "/".join(parts[:2])


def _epoch(ts: str) -> float:
    return datetime.fromisoformat(ts).timestamp()


def collect(fetch_json: Callable[[str], Any], *, repos: dict[str, str], human, agent_logins: dict[str, str],
            live_branches: dict[str, list[str]], lookback_days: int, now: int) -> list[Item]:
    cutoff = now - lookback_days * 86400
    items: list[Item] = []
    for repo, project in repos.items():
        prs = fetch_json(f"{API}/repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=50")
        if not isinstance(prs, list):
            raise SourceError("unexpected GitHub response")
        for pr in prs:
            try:
                if _epoch(pr["updated_at"]) < cutoff:
                    continue
                checks = reviews = []
                if pr.get("state") == "open" and not pr.get("draft"):
                    checks = _fetch_check_runs(
                        fetch_json, f"{API}/repos/{repo}/commits/{pr['head']['sha']}/check-runs?per_page=100")
                    reviews = _fetch_reviews(
                        fetch_json, f"{API}/repos/{repo}/pulls/{pr['number']}/reviews?per_page=100")
                pr = dict(pr, _repo=repo)
                items.append(map_pr(pr, checks=checks, reviews=reviews, project_key=project, human=human,
                                    agent_logins=agent_logins, live_branches=live_branches.get(repo, [])))
            except (KeyError, TypeError, ValueError, AttributeError):
                raise SourceError("unexpected GitHub response") from None
    return items


MAX_PAGES = 20
PER_PAGE = 100


def _fetch_check_runs(fetch_json, url: str) -> dict:
    runs: list = []
    total = None
    for page in range(1, MAX_PAGES + 1):
        data = fetch_json(url if page == 1 else f"{url}&page={page}")
        if not isinstance(data, dict):
            raise SourceError("unexpected GitHub response")
        batch = data.get("check_runs") or []
        total = data.get("total_count", len(batch)) if total is None else total
        runs += batch
        if not batch or len(runs) >= total:
            return {"total_count": total, "check_runs": runs}
    raise SourceError("too many check runs to fetch")


def _fetch_reviews(fetch_json, url: str) -> list:
    reviews: list = []
    for page in range(1, MAX_PAGES + 1):
        batch = fetch_json(url if page == 1 else f"{url}&page={page}")
        if not isinstance(batch, list):
            raise SourceError("unexpected GitHub response")
        reviews += batch
        if len(batch) < PER_PAGE:
            return reviews
    raise SourceError("too many reviews to fetch")


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_prefix: str):
        self.allowed_prefix = allowed_prefix

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith(self.allowed_prefix):
            raise SourceError("GitHub redirected to an unexpected host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_fetch_json(token: str, *, allowed_prefix: str = API + "/") -> Callable[[str], Any]:
    opener = urllib.request.build_opener(_SameHostRedirects(allowed_prefix))

    def fetch(url: str) -> Any:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "loopboard-connector"})
        try:
            with opener.open(req, timeout=30) as resp:
                if resp.status != 200:
                    raise SourceError(f"GitHub returned HTTP {resp.status}")
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise SourceError(f"GitHub returned HTTP {e.code}") from None
        except (urllib.error.URLError, OSError):
            raise SourceError("GitHub request failed") from None
        except ValueError:
            raise SourceError("GitHub returned invalid JSON") from None
    return fetch
