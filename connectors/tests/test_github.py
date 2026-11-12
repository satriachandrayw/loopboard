import json
from pathlib import Path

import pytest

from loopboard_connectors import cli, github
from loopboard_connectors.contract import SourceError

FIX = Path(__file__).parent / "fixtures" / "github"
TOKEN = "lb_supersecrettoken"
GH_TOKEN = "ghp_supersecretgithub"
NOW = 1794556800  # 2026-11-12T08:00:00Z
AGENTS = {"builder-bot": "builder"}
BASE = "https://api.github.com/repos/owner/app"


def fake_fetch(url):
    if url.startswith(BASE + "/pulls?"):
        return json.loads((FIX / "pulls.json").read_text())
    if "/check-runs" in url:
        sha = url.split("/commits/")[1].split("/")[0]
        return json.loads((FIX / f"checks-{sha}.json").read_text())
    if "/reviews" in url:
        n = url.split("/pulls/")[1].split("/")[0]
        p = FIX / f"reviews-{n}.json"
        return json.loads(p.read_text()) if p.exists() else []
    raise AssertionError(url)


def collect(fetch=fake_fetch, live=None, lookback=14):
    items = github.collect(fetch, repos={"owner/app": "DEMO"}, human="owner", agent_logins=AGENTS,
                           live_branches=live or {}, lookback_days=lookback, now=NOW)
    return {i.external_id: i for i in items}


def pair(i):
    return (i.status_category, i.waiting_on)


def test_draft_pr_is_in_progress_waiting_on_mapped_agent():
    i = collect()["owner/app#1"]
    assert pair(i) == ("in_progress", "agent:builder")
    assert i.owner == "agent:builder" and i.raw_status == "draft"


def test_open_pr_with_failing_check_waits_on_author_agent():
    assert pair(collect()["owner/app#2"]) == ("review", "agent:builder")


def test_open_pr_with_pending_check_waits_on_ci():
    assert pair(collect()["owner/app#3"]) == ("review", "source:CI")


def test_open_green_pr_waits_on_human():
    i = collect()["owner/app#4"]
    assert pair(i) == ("review", "human:owner")
    assert i.raw_status == "open" and i.project_key == "DEMO" and i.next_step is None
    assert i.url == "https://github.com/owner/app/pull/4"
    assert i.last_activity_at == "2026-11-12T08:00:00Z"


def test_changes_requested_waits_on_author_agent():
    assert pair(collect()["owner/app#10"]) == ("review", "agent:builder")


def test_latest_review_per_reviewer_wins():
    pr = json.loads((FIX / "pulls.json").read_text())[3]
    rv = [{"user": {"login": "a"}, "state": "CHANGES_REQUESTED", "submitted_at": "2026-11-12T01:00:00Z"},
          {"user": {"login": "a"}, "state": "APPROVED", "submitted_at": "2026-11-12T02:00:00Z"}]
    i = github.map_pr(pr, checks=[], reviews=rv, project_key="DEMO", human="owner",
                      agent_logins=AGENTS, live_branches=[])
    assert i.waiting_on == "human:owner"


def test_merged_pr_has_merged_at_and_no_live_at():
    i = collect()["owner/app#5"]
    assert pair(i) == ("review", "human:owner")
    assert i.merged_at == "2026-11-11T10:00:00Z" and i.live_at is None and i.raw_status == "merged"


def test_merge_into_live_branch_sets_live_at():
    items = collect(live={"owner/app": ["main"]})
    assert items["owner/app#6"].live_at == items["owner/app#6"].merged_at == "2026-11-11T11:00:00Z"
    assert items["owner/app#5"].live_at is None


def test_closed_unmerged_is_canceled():
    i = collect()["owner/app#7"]
    assert pair(i) == ("canceled", None) and i.raw_status == "closed"


def test_unmapped_author_waits_on_human():
    i = collect()["owner/app#8"]
    assert i.waiting_on == "human:owner" and i.owner is None


def test_lookback_skips_old_prs():
    assert "owner/app#9" not in collect()
    assert "owner/app#9" in collect(lookback=100000)


def test_title_truncated():
    pr = dict(json.loads((FIX / "pulls.json").read_text())[3], title="x" * 500)
    i = github.map_pr(pr, checks=[], reviews=[], project_key="DEMO", human="owner",
                      agent_logins=AGENTS, live_branches=[])
    assert len(i.title) == 300


def test_fetch_failure_raises_source_error():
    def boom(url):
        raise SourceError("GitHub returned HTTP 500")
    with pytest.raises(SourceError):
        collect(boom)


# CLI

def cfg(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[loopboard]\nurl = "https://lb.example.test/"\ntoken_env = "LB_TOKEN"\n'
                 '[general]\nhuman = "owner"\n[github]\ntoken_env = "GH_TOKEN"\n'
                 '[github.repos]\n"owner/app" = "DEMO"\n[github.agents]\nbuilder-bot = "builder"\n'
                 '[github.live_branches]\n"owner/app" = ["main"]\n')
    return p


class Poster:
    def __init__(self):
        self.calls = []

    def __call__(self, url, body, headers):
        payload = json.loads(body)
        self.calls.append((url, payload, headers))
        n = len(payload["items"])
        return {"accepted": n, "created": n, "updated": 0, "skipped_older": 0}


def run(tmp_path, capsys, *extra, fetch=fake_fetch, post=None, env=None):
    e = {"LB_TOKEN": TOKEN, "GH_TOKEN": GH_TOKEN} if env is None else env
    code = cli.main(["sync", "github", "--config", str(cfg(tmp_path)), *extra],
                    env=e, post=post, fetch_json=fetch)
    o = capsys.readouterr()
    return code, o.out, o.err


def test_cli_happy_path(tmp_path, capsys):
    post = Poster()
    code, out, _ = run(tmp_path, capsys, post=post)
    assert code == 0
    s = json.loads(out.strip().splitlines()[-1])
    assert s["connector"] == "github" and s["collected"] == 9 and s["posts"] == 1
    url, payload, _ = post.calls[0]
    assert payload["source"] == "github"
    by = {i["external_id"]: i for i in payload["items"]}
    assert by["owner/app#6"]["live_at"] == "2026-11-11T11:00:00Z"


def test_cli_github_fetch_failure_exits_1_posts_nothing(tmp_path, capsys):
    post = Poster()

    def boom(url):
        raise SourceError("GitHub returned HTTP 502")
    code, out, _ = run(tmp_path, capsys, post=post, fetch=boom)
    assert code == 1 and post.calls == []
    assert json.loads(out.strip().splitlines()[-1])["connector"] == "github"


def test_token_never_in_output(tmp_path, capsys):
    def leaky(url):
        raise SourceError(f"failed with {GH_TOKEN} and {TOKEN}")
    for fetch, post in ((fake_fetch, Poster()), (leaky, Poster())):
        code, out, err = run(tmp_path, capsys, post=post, fetch=fetch)
        assert TOKEN not in out + err and GH_TOKEN not in out + err


def test_missing_github_token_exits_2(tmp_path, capsys):
    code, out, _ = run(tmp_path, capsys, post=Poster(), env={"LB_TOKEN": TOKEN})
    assert code == 2 and GH_TOKEN not in out


def test_cli_rejects_bad_config_types(tmp_path, capsys):
    p = cfg(tmp_path)
    p.write_text(p.read_text().replace('["main"]', '"main"'))
    code = cli.main(["sync", "github", "--config", str(p)],
                    env={"LB_TOKEN": TOKEN, "GH_TOKEN": GH_TOKEN}, post=Poster(), fetch_json=fake_fetch)
    out = capsys.readouterr().out
    assert code == 2 and "live_branches" in out


def test_no_checks_or_reviews_fetched_for_draft_closed_merged():
    seen = []

    def rec(url):
        seen.append(url)
        return fake_fetch(url)
    collect(rec)
    for n in (1, 5, 6, 7):
        assert not any(f"sha{n}" in u or f"/pulls/{n}/" in u for u in seen)
    assert sum("/check-runs" in u for u in seen) == 5  # open non-draft PRs: 2, 3, 4, 8, 10


def test_checks_and_reviews_fetch_100_per_page():
    seen = []

    def rec(url):
        seen.append(url)
        return fake_fetch(url)
    collect(rec)
    sub = [u for u in seen if "/check-runs" in u or "/reviews" in u]
    assert sub and all(u.endswith("?per_page=100") for u in sub), sub


def test_redirect_off_host_raises_and_never_forwards_token():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"[]")

        def log_message(self, *a):
            pass

    target = HTTPServer(("127.0.0.1", 0), Target)

    class Redirector(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(301)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/x")
            self.end_headers()

        def log_message(self, *a):
            pass

    redir = HTTPServer(("127.0.0.1", 0), Redirector)
    for srv in (target, redir):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{redir.server_port}/"
        fetch = github.default_fetch_json(GH_TOKEN, allowed_prefix=base)
        with pytest.raises(SourceError) as ei:
            fetch(base + "repos")
        assert GH_TOKEN not in str(ei.value)
        assert seen == []
    finally:
        target.shutdown()
        redir.shutdown()


def test_github_refuses_non_https_remote(tmp_path, capsys):
    p = cfg(tmp_path)
    p.write_text(p.read_text().replace("https://lb.example.test/", "http://lb.example.test/"))
    post = Poster()
    code = cli.main(["sync", "github", "--config", str(p)],
                    env={"LB_TOKEN": TOKEN, "GH_TOKEN": GH_TOKEN}, post=post, fetch_json=fake_fetch)
    assert code == 2 and post.calls == []


def test_github_allows_localhost_http(tmp_path, capsys):
    p = cfg(tmp_path)
    p.write_text(p.read_text().replace("https://lb.example.test/", "http://localhost:8799"))
    post = Poster()
    code = cli.main(["sync", "github", "--config", str(p)],
                    env={"LB_TOKEN": TOKEN, "GH_TOKEN": GH_TOKEN}, post=post, fetch_json=fake_fetch)
    assert code == 0


def _green(i):
    return {"id": i, "status": "completed", "conclusion": "success"}


def test_check_runs_follow_pagination():
    seen = []

    def f(url):
        if "/check-runs" in url:
            seen.append(url)
            if "page=2" in url:
                runs = [_green(i) for i in range(100, 149)] + [
                    {"id": 999, "status": "completed", "conclusion": "failure"}]
            else:
                runs = [_green(i) for i in range(100)]
            return {"total_count": 150, "check_runs": runs}
        return fake_fetch(url)

    def all_green(url):
        if "/check-runs" in url:
            return {"total_count": 100, "check_runs": [_green(i) for i in range(100)]}
        return fake_fetch(url)
    items = collect(f)
    base = collect(all_green)
    assert any("page=2" in u for u in seen)
    assert not any("page=3" in u for u in seen)
    assert any(items[k].waiting_on != base[k].waiting_on for k in items)


def test_check_runs_pagination_stops_on_empty_page():
    calls = []

    def f(url):
        if "/check-runs" in url:
            calls.append(url)
            return {"total_count": 150, "check_runs": [_green(i) for i in range(100)] if "&page=" not in url else []}
        return fake_fetch(url)
    collect(f)
    assert len(calls) == 10  # 5 open PRs x (page 1, empty page 2)


def test_reviews_follow_pagination():
    seen = []
    page1 = [{"user": {"login": f"u{i}"}, "state": "APPROVED", "submitted_at": "2025-01-01T00:00:00Z"}
             for i in range(100)]
    page2 = [{"user": {"login": "late"}, "state": "CHANGES_REQUESTED", "submitted_at": "2025-01-02T00:00:00Z"}]

    def f(url):
        if "/reviews" in url:
            seen.append(url)
            return page2 if "page=2" in url else page1
        if "/check-runs" in url:
            return {"total_count": 0, "check_runs": []}
        return fake_fetch(url)
    items = collect(f)
    base = collect(lambda u: [] if "/reviews" in u else (
        {"total_count": 0, "check_runs": []} if "/check-runs" in u else fake_fetch(u)))
    assert any("page=2" in u for u in seen)
    assert any(items[k].waiting_on != base[k].waiting_on for k in items)


def test_unbounded_pagination_is_a_source_error():
    def f(url):
        if "/check-runs" in url:
            return {"total_count": 10**9, "check_runs": [_green(1)] * 100}
        return fake_fetch(url)
    with pytest.raises(SourceError):
        collect(f)


# D23a: a release PR into a live branch brings earlier feature PRs live

REL = "https://api.github.com/repos/owner/rel"


def _merged(n, merged_at, base, sha=None):
    return {"number": n, "title": f"PR {n}", "state": "closed", "draft": False, "merged_at": merged_at,
            "merge_commit_sha": sha if sha is not None else f"m{n}",
            "html_url": f"https://github.com/owner/rel/pull/{n}", "updated_at": "2026-11-12T08:00:00Z",
            "user": {"login": "builder-bot"}, "head": {"sha": f"h{n}"}, "base": {"ref": base}}


REL_PRS = [
    _merged(21, "2026-11-05T10:00:00Z", "development"),
    _merged(22, "2026-11-10T10:00:00Z", "development"),
    _merged(30, "2026-11-07T12:00:00Z", "main"),  # release: development -> main
    _merged(31, "2026-11-09T12:00:00Z", "main"),  # a later release
]


def _commits(shas):
    return {"status": "ahead", "total_commits": len(shas), "commits": [{"sha": s} for s in shas]}


def rel_fetch(compare, prs=REL_PRS, seen=None):
    """compare(live, base, page) answers GET compare/{live}...{base}; it returns the dict or raises."""
    def f(url):
        if seen is not None:
            seen.append(url)
        if url.startswith(REL + "/pulls?"):
            page = int(url.split("&page=")[1])
            return prs[(page - 1) * 100: page * 100]
        if url.startswith(REL + "/compare/"):
            path, query = url.split("/compare/")[1].split("?")
            live, base = path.split("...")
            q = dict(p.split("=", 1) for p in query.split("&"))
            assert q["per_page"] == "250", url
            return compare(live, base, int(q["page"]))
        raise AssertionError(url)
    return f


def rel_collect(fetch, lookback=14):
    items = github.collect(fetch, repos={"owner/rel": "REL"}, human="owner", agent_logins=AGENTS,
                           live_branches={"owner/rel": ["main"]}, lookback_days=lookback, now=NOW)
    return {i.external_id: i for i in items}


def none_missing(live, base, page):
    return _commits([])  # main has every commit of development


def test_feature_pr_into_development_becomes_live_when_main_contains_it():
    seen = []
    items = rel_collect(rel_fetch(none_missing, seen=seen))
    i = items["owner/rel#21"]
    assert i.live_at == "2026-11-07T12:00:00Z"  # earliest release merged at or after 2026-11-05
    assert i.merged_at == "2026-11-05T10:00:00Z" and i.raw_status == "merged"
    assert [u for u in seen if "/compare/" in u] == [f"{REL}/compare/main...development?per_page=250&page=1"]


def test_merge_sha_in_compare_stays_merged_not_live():
    items = rel_collect(rel_fetch(lambda live, base, page: _commits(["x1", "m21", "m22", "x2"])))
    for n in (21, 22):
        assert items[f"owner/rel#{n}"].live_at is None
        assert items[f"owner/rel#{n}"].raw_status == "merged"


def test_release_check_uses_one_branch_compare():
    prs = [_merged(100 + k, f"2026-11-{1 + k // 24:02d}T{k % 24:02d}:00:00Z", "development") for k in range(100)]
    prs.reverse()  # the listing is newest-first
    prs.append(_merged(30, "2026-11-11T12:00:00Z", "main"))  # release after every feature PR
    seen = []
    items = rel_collect(rel_fetch(lambda live, base, page: _commits(["m150", "m199", "other"]), prs=prs,
                                  seen=seen))
    assert len([u for u in seen if "/compare/" in u]) == 1
    not_live = {k for k, i in items.items() if i.raw_status == "merged" and i.live_at is None}
    assert not_live == {"owner/rel#150", "owner/rel#199"}
    assert items["owner/rel#100"].live_at == "2026-11-11T12:00:00Z"
    assert sum(1 for i in items.values() if i.live_at) == 98 + 1  # 98 features plus the release itself


def test_branch_compare_pages():
    calls = []

    def compare(live, base, page):
        calls.append(page)
        if page == 1:
            return _commits([f"x{k}" for k in range(250)])
        return _commits(["m22"] + [f"y{k}" for k in range(9)])
    items = rel_collect(rel_fetch(compare))
    assert calls == [1, 2]
    assert items["owner/rel#21"].live_at == "2026-11-07T12:00:00Z"
    assert items["owner/rel#22"].live_at is None  # on page 2


def test_branch_compare_page_cap_raises_source_error():
    pages = []

    def compare(live, base, page):
        pages.append(page)
        return _commits([f"x{page}-{k}" for k in range(250)])
    with pytest.raises(SourceError):
        rel_collect(rel_fetch(compare))
    assert len(pages) == github.MAX_PAGES


def test_one_compare_per_base_and_live_branch():
    prs = REL_PRS + [_merged(23, "2026-11-06T10:00:00Z", "staging")]
    seen = []
    items = github.collect(rel_fetch(none_missing, prs=prs, seen=seen), repos={"owner/rel": "REL"},
                           human="owner", agent_logins=AGENTS,
                           live_branches={"owner/rel": ["main", "prod"]}, lookback_days=14, now=NOW)
    compares = sorted(u.split("/compare/")[1].split("?")[0] for u in seen if "/compare/" in u)
    assert compares == ["main...development", "main...staging", "prod...development", "prod...staging"]
    assert all(i.live_at for i in items)


def test_live_in_any_live_branch():
    def compare(live, base, page):
        return _commits(["m21", "m22"] if live == "main" else ["m22"])
    items = github.collect(rel_fetch(compare), repos={"owner/rel": "REL"}, human="owner",
                           agent_logins=AGENTS, live_branches={"owner/rel": ["main", "prod"]},
                           lookback_days=14, now=NOW)
    by = {i.external_id: i for i in items}
    assert by["owner/rel#21"].live_at == github._iso(NOW)  # prod contains it; no release PR into prod
    assert by["owner/rel#22"].live_at is None


@pytest.mark.parametrize("code", [404, 422])
def test_branch_compare_404_means_not_live(code):
    def compare(live, base, page):
        raise github.GitHubHTTPError(code)
    items = rel_collect(rel_fetch(compare))
    assert items["owner/rel#21"].live_at is None and items["owner/rel#22"].live_at is None
    assert items["owner/rel#30"].live_at == "2026-11-07T12:00:00Z"  # into main: unaffected


def test_compare_500_fails_run():
    def compare(live, base, page):
        raise github.GitHubHTTPError(500)
    with pytest.raises(SourceError):
        rel_collect(rel_fetch(compare))


def test_compare_unexpected_body_fails_run():
    with pytest.raises(SourceError):
        rel_collect(rel_fetch(lambda live, base, page: {"commits": "nope"}))


def test_compare_skips_prs_merged_before_lookback():
    prs = [_merged(40, "2026-10-01T10:00:00Z", "development"), _merged(30, "2026-11-07T12:00:00Z", "main")]
    seen = []
    items = rel_collect(rel_fetch(none_missing, prs=prs, seen=seen))
    assert not any("/compare/" in u for u in seen)
    assert items["owner/rel#40"].live_at is None


def test_merged_pr_without_merge_sha_stays_not_live():
    prs = [_merged(21, "2026-11-05T10:00:00Z", "development", sha=""), REL_PRS[2]]
    seen = []
    items = rel_collect(rel_fetch(none_missing, prs=prs, seen=seen))
    assert not any("/compare/" in u for u in seen) and items["owner/rel#21"].live_at is None
    prs = [_merged(21, "2026-11-05T10:00:00Z", "development", sha=""), REL_PRS[1], REL_PRS[2]]
    items = rel_collect(rel_fetch(none_missing, prs=prs))
    assert items["owner/rel#21"].live_at is None  # compared branch, but no sha to clear
    assert items["owner/rel#22"].live_at is not None


def test_compare_branch_names_are_quoted():
    prs = [_merged(21, "2026-11-05T10:00:00Z", "feat/a b"), REL_PRS[2]]
    seen = []
    rel_collect(rel_fetch(none_missing, prs=prs, seen=seen))
    assert [u for u in seen if "/compare/" in u] == [f"{REL}/compare/main...feat/a%20b?per_page=250&page=1"]


def test_pr_into_live_branch_unchanged():
    seen = []
    items = rel_collect(rel_fetch(none_missing, seen=seen))
    for n, at in ((30, "2026-11-07T12:00:00Z"), (31, "2026-11-09T12:00:00Z")):
        assert items[f"owner/rel#{n}"].live_at == items[f"owner/rel#{n}"].merged_at == at
    assert not any("...main?" in u for u in seen)


def test_no_release_pr_found_uses_run_time():
    items = rel_collect(rel_fetch(none_missing))
    i = items["owner/rel#22"]  # merged 2026-11-10, after every release PR in the listing
    assert i.live_at == "2026-11-13T08:00:00Z" == github._iso(NOW)  # the run time
    assert i.merged_at == "2026-11-10T10:00:00Z"


def test_github_http_error_is_a_source_error_with_status():
    e = github.GitHubHTTPError(404)
    assert isinstance(e, SourceError) and e.status == 404 and "404" in str(e)


# Pagination of the pulls listing (v1a.3)

PAGED = "https://api.github.com/repos/owner/busy"


def _iso_at(ts):
    return github._iso(ts)


def _pr(n, updated, state="closed", merged=True, draft=False, base="main"):
    return {"number": n, "title": f"PR {n}", "state": state, "draft": draft,
            "merged_at": _iso_at(updated) if state == "closed" and merged else None,
            "merge_commit_sha": f"m{n}", "html_url": f"https://github.com/owner/busy/pull/{n}",
            "updated_at": _iso_at(updated), "user": {"login": "builder-bot"},
            "head": {"sha": f"h{n}"}, "base": {"ref": base}}


def paged_fetch(prs, seen, per_page=100):
    """Serves `prs` (already sorted updated desc) as GitHub would, 100 per page; records every URL."""
    def f(url):
        seen.append(url)
        if url.startswith(PAGED + "/pulls?"):
            q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
            assert q["per_page"] == "100" and q["sort"] == "updated" and q["direction"] == "desc", url
            page = int(q.get("page", "1"))
            return prs[(page - 1) * per_page: page * per_page]
        if "/check-runs" in url:
            return {"total_count": 0, "check_runs": []}
        if "/reviews" in url:
            return []
        if url.startswith(PAGED + "/compare/"):
            return {"status": "ahead", "total_commits": 2, "commits": [{"sha": "m1950"}, {"sha": "x"}]}
        raise AssertionError(url)
    return f


def paged_collect(fetch, lookback=14, live=None):
    items = github.collect(fetch, repos={"owner/busy": "BUSY"}, human="owner", agent_logins=AGENTS,
                           live_branches=live or {}, lookback_days=lookback, now=NOW)
    return {i.external_id: i for i in items}


def _listing_calls(seen):
    return [u for u in seen if u.startswith(PAGED + "/pulls?")]


def test_pages_until_older_than_cutoff():
    cutoff = NOW - 14 * 86400
    # pages 1-2 inside the window; page 3 crosses the cutoff halfway; page 4 would be all old
    prs = [_pr(1000 - k, NOW - 60 - k * 3000) for k in range(250)]
    prs += [_pr(500 - k, cutoff - 3600 - k * 60) for k in range(150)]
    assert _epoch_ok(prs)
    seen = []
    items = paged_collect(paged_fetch(prs, seen))
    calls = _listing_calls(seen)
    assert len(calls) == 3 and calls[2].endswith("&page=3"), calls
    assert len(items) == 250  # the old half of page 3 is still filtered out


def _epoch_ok(prs):
    ts = [github._epoch(p["updated_at"]) for p in prs]
    return ts == sorted(ts, reverse=True)


def test_stops_on_empty_page():
    prs = [_pr(1000 - k, NOW - 60 - k * 60) for k in range(200)]  # exactly two full pages, all recent
    seen = []
    items = paged_collect(paged_fetch(prs, seen))
    calls = _listing_calls(seen)
    assert len(calls) == 3 and calls[2].endswith("&page=3"), calls  # page 3 is empty
    assert len(items) == 200


def test_page_cap_raises_source_error():
    seen = []

    def endless(url):
        seen.append(url)
        if url.startswith(PAGED + "/pulls?"):
            return [_pr(k, NOW - 60) for k in range(100)]  # always a full page inside the window
        raise AssertionError(url)
    with pytest.raises(SourceError):
        paged_collect(endless)
    assert len(_listing_calls(seen)) == github.MAX_PAGES


def test_all_prs_within_lookback_collected():
    prs = [_pr(2000 - k, NOW - 60 - k * 7000) for k in range(164)]  # 164 PRs over ~13.3 days
    prs += [_pr(100 - k, NOW - 15 * 86400 - k * 60) for k in range(80)]  # older than lookback
    assert _epoch_ok(prs)
    seen = []
    items = paged_collect(paged_fetch(prs, seen))
    assert len(items) == 164
    assert len(_listing_calls(seen)) == 2


def test_api_call_budget_for_164_pr_repo():
    # 164 PRs inside the window: 12 open (8 ready, 4 draft), 120 merged into development,
    # 10 release PRs merged into main, 22 closed unmerged
    prs = []
    for k in range(164):
        ts = NOW - 60 - k * 7000
        if k < 8:
            prs.append(_pr(2000 - k, ts, state="open", merged=False))
        elif k < 12:
            prs.append(_pr(2000 - k, ts, state="open", merged=False, draft=True))
        elif k < 132:
            prs.append(_pr(2000 - k, ts, base="development"))
        elif k < 142:
            prs.append(_pr(2000 - k, ts))
        else:
            prs.append(_pr(2000 - k, ts, merged=False))
    prs += [_pr(100 - k, NOW - 15 * 86400 - k * 60) for k in range(80)]
    seen = []
    items = paged_collect(paged_fetch(prs, seen), live={"owner/busy": ["main"]})
    listing = len(_listing_calls(seen))
    checks = sum("/check-runs" in u for u in seen)
    reviews = sum("/reviews" in u for u in seen)
    compares = [u for u in seen if "/compare/" in u]
    # per-PR calls only for open, non-draft PRs; merged/closed PRs need neither (map_pr ignores them)
    # D23a: one compare per (repo, non-live base, live branch), not one per merged PR
    assert (listing, checks, reviews, len(compares)) == (2, 8, 8, 1)
    assert compares == [f"{PAGED}/compare/main...development?per_page=250&page=1"]
    assert len(seen) == 19
    assert sum(1 for i in items.values() if i.raw_status == "merged" and i.live_at is None) == 1
    # 10 such repos: 190 calls per run, well under 1,000
    assert 10 * len(seen) < 1000
