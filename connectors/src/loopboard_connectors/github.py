"""GitHub pull request connector (read-only). Mapping rules: D19, D23, D23a, R10."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .client import USER_AGENT
from .contract import Item, SourceError, split_epic_prefix

API = "https://api.github.com"
TITLE_MAX = 300
COMPARE_PER_PAGE = 250  # GitHub's maximum for the compare endpoint
NOT_CONTAINED_HTTP = {404, 422}  # e.g. a deleted base branch
FAILING = {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}


class GitHubHTTPError(SourceError):
    """GitHub answered with a non-2xx status."""

    def __init__(self, status: int):
        super().__init__(f"GitHub returned HTTP {status}")
        self.status = status


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
    epic_key, title = split_epic_prefix(pr.get("title") or "")
    return Item(source="github", external_id=f"{repo}#{repo_number}",
                title=title[:TITLE_MAX], url=html or None,
                status_category=cat, raw_status=raw, owner=agent_tag, waiting_on=waiting,
                blocked_reason=None, next_step=None, project_key=project_key, epic_key=epic_key,
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
    listings: dict[str, list[dict]] = {}
    for repo, project in repos.items():
        prs = _fetch_pulls(fetch_json, repo, cutoff)
        listings[repo] = prs
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
    try:
        return _mark_released(fetch_json, items, listings, live_branches=live_branches, cutoff=cutoff, now=now)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SourceError("unexpected GitHub response") from None


def _mark_released(fetch_json, items: list[Item], listings: dict[str, list[dict]], *,
                   live_branches: dict[str, list[str]], cutoff: int, now: int) -> list[Item]:
    """D23a: a merged PR whose base B is not live becomes live once a live branch L contains its merge commit.

    One branch compare per (repo, B, L) lists the commits B has and L lacks; a PR is live in L iff its
    merge_commit_sha is not among them.
    """
    by_id = {i.external_id: k for k, i in enumerate(items)}
    for repo, prs in listings.items():
        live = live_branches.get(repo, [])
        if not live:
            continue
        releases: dict[str, list[tuple[float, str]]] = {b: [] for b in live}  # L -> (merged_at epoch, iso)
        candidates: dict[str, list[tuple[float, dict]]] = {}  # B -> [(merged_at epoch, pr)]
        for pr in prs:
            merged_at = pr.get("merged_at")
            if pr.get("state") != "closed" or not merged_at:
                continue
            base = (pr.get("base") or {}).get("ref")
            if base in live:
                releases[base].append((_epoch(merged_at), merged_at))
            elif pr.get("merge_commit_sha") and f"{repo}#{pr['number']}" in by_id \
                    and _epoch(merged_at) >= cutoff:
                candidates.setdefault(base, []).append((_epoch(merged_at), pr))
        for base, merged_prs in candidates.items():
            live_at: dict[int, str] = {}
            for branch in live:
                missing = _missing_from(fetch_json, repo, branch, base)
                if missing is None:  # 404/422: nothing into this base counts as live in this branch
                    continue
                rel = sorted(releases[branch])
                for merged, pr in merged_prs:
                    if pr["merge_commit_sha"] in missing:
                        continue
                    later = [iso for t, iso in rel if t >= merged]
                    at = later[0] if later else _iso(now)
                    if pr["number"] not in live_at or _epoch(at) < _epoch(live_at[pr["number"]]):
                        live_at[pr["number"]] = at
            for number, at in live_at.items():
                k = by_id[f"{repo}#{number}"]
                items[k] = replace(items[k], live_at=at)
    return items


def _missing_from(fetch_json, repo: str, live: str, base: str) -> set[str] | None:
    """SHAs of commits on `base` that `live` lacks, or None if GitHub cannot compare the branches."""
    q = urllib.parse.quote
    url = f"{API}/repos/{repo}/compare/{q(live, safe='/')}...{q(base, safe='/')}?per_page={COMPARE_PER_PAGE}"
    shas: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        try:
            data = fetch_json(f"{url}&page={page}")
        except GitHubHTTPError as e:
            if e.status in NOT_CONTAINED_HTTP:
                return None
            raise
        commits = data.get("commits") if isinstance(data, dict) else None
        if not isinstance(commits, list):
            raise SourceError("unexpected GitHub response")
        shas.update(c["sha"] for c in commits)
        if len(commits) < COMPARE_PER_PAGE:
            return shas
    raise SourceError("too many commits to compare")


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


MAX_PAGES = 20
PER_PAGE = 100


def _fetch_pulls(fetch_json, repo: str, cutoff: float) -> list[dict]:
    """Pages the pulls listing (updated desc) until a page is empty or short, or ends before the cutoff."""
    url = f"{API}/repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page={PER_PAGE}"
    prs: list[dict] = []
    seen: set = set()
    for page in range(1, MAX_PAGES + 1):
        batch = fetch_json(f"{url}&page={page}")
        if not isinstance(batch, list):
            raise SourceError("unexpected GitHub response")
        try:
            for pr in batch:
                if pr["number"] not in seen:  # a PR updated mid-run can move onto a later page
                    seen.add(pr["number"])
                    prs.append(pr)
            if len(batch) < PER_PAGE or _epoch(batch[-1]["updated_at"]) < cutoff:
                return prs
        except (KeyError, TypeError, ValueError, AttributeError):
            raise SourceError("unexpected GitHub response") from None
    raise SourceError("too many pull requests to fetch")


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
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": USER_AGENT})
        try:
            with opener.open(req, timeout=30) as resp:
                if resp.status != 200:
                    raise GitHubHTTPError(resp.status)
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise GitHubHTTPError(e.code) from None
        except (urllib.error.URLError, OSError):
            raise SourceError("GitHub request failed") from None
        except ValueError:
            raise SourceError("GitHub returned invalid JSON") from None
    return fetch
