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


def rel_fetch(compare, prs=REL_PRS, seen=None):
    def f(url):
        if seen is not None:
            seen.append(url)
        if url.startswith(REL + "/pulls?"):
            return prs
        if url.startswith(REL + "/compare/"):
            sha, branch = url.split("/compare/")[1].split("?")[0].split("...")
            return compare(sha, branch)
        raise AssertionError(url)
    return f


def rel_collect(fetch, lookback=14):
    items = github.collect(fetch, repos={"owner/rel": "REL"}, human="owner", agent_logins=AGENTS,
                           live_branches={"owner/rel": ["main"]}, lookback_days=lookback, now=NOW)
    return {i.external_id: i for i in items}


def test_feature_pr_into_development_becomes_live_when_main_contains_it():
    seen = []
    items = rel_collect(rel_fetch(lambda sha, b: {"status": "ahead"}, seen=seen))
    i = items["owner/rel#21"]
    assert i.live_at == "2026-11-07T12:00:00Z"  # earliest release merged at or after 2026-11-05
    assert i.merged_at == "2026-11-05T10:00:00Z" and i.raw_status == "merged"
    assert f"{REL}/compare/m21...main?per_page=1" in seen


@pytest.mark.parametrize("status", ["behind", "diverged"])
def test_not_contained_stays_merged_not_live(status):
    items = rel_collect(rel_fetch(lambda sha, b: {"status": status}))
    for n in (21, 22):
        assert items[f"owner/rel#{n}"].live_at is None
        assert items[f"owner/rel#{n}"].raw_status == "merged"


@pytest.mark.parametrize("code", [404, 422])
def test_compare_404_is_not_contained(code):
    def compare(sha, branch):
        raise github.GitHubHTTPError(code)
    items = rel_collect(rel_fetch(compare))
    assert items["owner/rel#21"].live_at is None and items["owner/rel#22"].live_at is None


def test_compare_500_fails_run():
    def compare(sha, branch):
        raise github.GitHubHTTPError(500)
    with pytest.raises(SourceError):
        rel_collect(rel_fetch(compare))


def test_compare_budget_60():
    prs = [_merged(100 + k, f"2026-11-{1 + k // 24:02d}T{k % 24:02d}:00:00Z", "development") for k in range(70)]
    prs.reverse()  # the listing is newest-first; the budget goes to the oldest
    seen = []
    items = rel_collect(rel_fetch(lambda sha, b: {"status": "behind"}, prs=prs, seen=seen))
    compared = [u.split("/compare/")[1].split("...")[0] for u in seen if "/compare/" in u]
    assert compared == [f"m{100 + k}" for k in range(60)]
    assert all(i.live_at is None for i in items.values())


def test_compare_budget_is_per_run_across_repos():
    prs = [_merged(100 + k, f"2026-11-{1 + k // 24:02d}T{k % 24:02d}:00:00Z", "development") for k in range(40)]
    calls = []

    def f(url):
        if "/pulls?" in url:
            return prs
        calls.append(url)
        return {"status": "behind"}
    github.collect(f, repos={"owner/rel": "REL", "owner/rel2": "REL"}, human="owner", agent_logins=AGENTS,
                   live_branches={"owner/rel": ["main"], "owner/rel2": ["main"]}, lookback_days=14, now=NOW)
    assert len(calls) == 60


def test_compare_skips_prs_merged_before_lookback():
    prs = [_merged(40, "2026-10-01T10:00:00Z", "development"), _merged(30, "2026-11-07T12:00:00Z", "main")]
    seen = []
    items = rel_collect(rel_fetch(lambda sha, b: {"status": "ahead"}, prs=prs, seen=seen))
    assert not any("/compare/" in u for u in seen)
    assert items["owner/rel#40"].live_at is None


def test_compare_skipped_without_merge_commit_sha():
    prs = [_merged(21, "2026-11-05T10:00:00Z", "development", sha=""), REL_PRS[2]]
    seen = []
    items = rel_collect(rel_fetch(lambda sha, b: {"status": "ahead"}, prs=prs, seen=seen))
    assert not any("/compare/" in u for u in seen) and items["owner/rel#21"].live_at is None


def test_pr_into_live_branch_unchanged():
    seen = []
    items = rel_collect(rel_fetch(lambda sha, b: {"status": "ahead"}, seen=seen))
    for n, at in ((30, "2026-11-07T12:00:00Z"), (31, "2026-11-09T12:00:00Z")):
        assert items[f"owner/rel#{n}"].live_at == items[f"owner/rel#{n}"].merged_at == at
        assert not any(f"/compare/m{n}..." in u for u in seen)


def test_no_release_pr_found_uses_run_time():
    items = rel_collect(rel_fetch(lambda sha, b: {"status": "identical"}))
    i = items["owner/rel#22"]  # merged 2026-11-10, after every release PR in the listing
    assert i.live_at == "2026-11-13T08:00:00Z" == github._iso(NOW)  # the run time
    assert i.merged_at == "2026-11-10T10:00:00Z"


def test_github_http_error_is_a_source_error_with_status():
    e = github.GitHubHTTPError(404)
    assert isinstance(e, SourceError) and e.status == 404 and "404" in str(e)
