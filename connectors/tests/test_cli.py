import json
import shutil
from pathlib import Path

from loopboard_connectors import cli
from loopboard_connectors.contract import IngestRejected, SourceError

FIX = Path(__file__).parent / "fixtures" / "kanban"
TOKEN = "lb_supersecrettoken"


def cfg(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[loopboard]\nurl = "https://lb.example.test/"\ntoken_env = "LB_TOKEN"\n'
                 '[general]\nhuman = "owner"\n[kanban]\n[kanban.tenants]\ndemo = "DEMO"\n')
    return p


class Poster:
    def __init__(self):
        self.calls = []

    def __call__(self, url, body, headers):
        payload = json.loads(body)
        self.calls.append((url, payload, headers))
        n = len(payload["items"])
        return {"accepted": n, "created": n, "updated": 0, "skipped_older": 0}


def run(tmp_path, capsys, *extra, env=None, post=None, run_cli=None, replay=FIX):
    argv = ["sync", "kanban", "--config", str(cfg(tmp_path))]
    if replay is not None:
        argv += ["--cli-replay", str(replay)]
    argv += list(extra)
    e = {"LB_TOKEN": TOKEN} if env is None else env
    code = cli.main(argv, env=e, post=post, run_cli=run_cli)
    out = capsys.readouterr()
    return code, out.out, out.err


def summary(out):
    return json.loads(out.strip().splitlines()[-1])


def test_happy_path(tmp_path, capsys):
    post = Poster()
    code, out, _ = run(tmp_path, capsys, post=post)
    assert code == 0
    s = summary(out)
    assert (s["connector"], s["collected"], s["accepted"], s["posts"], s["dry_run"]) == ("kanban", 8, 8, 1, False)
    url, payload, headers = post.calls[0]
    assert url == "https://lb.example.test/api/ingest"
    assert payload["source"] == "kanban"
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert headers["Content-Type"] == "application/json"


def test_nonzero_exit_posts_nothing(tmp_path, capsys):
    post = Poster()

    def bad(argv):
        raise SourceError("hermes exited 1")

    code, out, _ = run(tmp_path, capsys, post=post, run_cli=bad, replay=None)
    assert code == 1 and post.calls == []
    assert "error" in summary(out)


def test_unparseable_output_posts_nothing(tmp_path, capsys):
    post = Poster()
    code, _, _ = run(tmp_path, capsys, post=post, run_cli=lambda a: "not json", replay=None)
    assert code == 1 and post.calls == []


def test_absent_items_are_untouched(tmp_path, capsys):
    d = tmp_path / "fx"
    shutil.copytree(FIX, d)
    post = Poster()
    run(tmp_path, capsys, post=post, replay=d)
    lst = json.loads((d / "list.json").read_text())[:3]
    (d / "list.json").write_text(json.dumps(lst))
    code, _, _ = run(tmp_path, capsys, post=post, replay=d)
    assert code == 0
    ids = [i["external_id"] for i in post.calls[1][1]["items"]]
    assert ids == ["1", "2", "3"]
    assert all(i["status_category"] != "canceled" for i in post.calls[1][1]["items"])


def test_empty_listing_posts_nothing_exits_0(tmp_path, capsys):
    post = Poster()
    code, out, _ = run(tmp_path, capsys, post=post, run_cli=lambda a: "[]", replay=None)
    assert code == 0 and post.calls == []
    s = summary(out)
    assert s["collected"] == 0 and s["posts"] == 0


def test_runner_splits_250_items_into_three_posts(tmp_path, capsys):
    d = tmp_path / "fx"
    d.mkdir()
    base = json.loads((FIX / "list.json").read_text())[1]
    lst = [dict(base, id=1000 + n) for n in range(250)]
    (d / "list.json").write_text(json.dumps(lst))
    for n in range(250):
        s = json.loads((FIX / "show-2.json").read_text())
        s["task"] = lst[n]
        (d / f"show-{1000 + n}.json").write_text(json.dumps(s))
    post = Poster()
    code, out, _ = run(tmp_path, capsys, post=post, replay=d)
    assert code == 0
    assert [len(c[1]["items"]) for c in post.calls] == [100, 100, 50]
    s = summary(out)
    assert s["posts"] == 3 and s["accepted"] == 250 and s["created"] == 250


def test_token_missing_exits_2(tmp_path, capsys):
    post = Poster()
    code, out, _ = run(tmp_path, capsys, env={}, post=post)
    assert code == 2 and post.calls == []


def test_missing_config_exits_2(tmp_path, capsys):
    code = cli.main(["sync", "kanban", "--config", str(tmp_path / "nope.toml")], env={})
    assert code == 2


def test_token_never_printed(tmp_path, capsys):
    def reject(url, body, headers):
        raise IngestRejected(403, f"forbidden {headers['Authorization']}")

    for post in (Poster(), reject):
        code, out, err = run(tmp_path, capsys, post=post)
        assert TOKEN not in out and TOKEN not in err
    code, out, err = run(tmp_path, capsys, env={})
    assert TOKEN not in out + err


def test_dry_run_posts_nothing(tmp_path, capsys):
    post = Poster()
    code, out, _ = run(tmp_path, capsys, "--dry-run", post=post)
    assert code == 0 and post.calls == []
    s = summary(out)
    assert s["dry_run"] is True and s["collected"] == 8 and s["posts"] == 0


def test_dry_run_needs_no_token(tmp_path, capsys):
    code, _, _ = run(tmp_path, capsys, "--dry-run", env={})
    assert code == 0


def test_ingest_422_exits_3(tmp_path, capsys):
    def reject(url, body, headers):
        raise IngestRejected(422, "unprocessable")

    code, out, _ = run(tmp_path, capsys, post=reject)
    assert code == 3
    assert "error" in summary(out)


def test_epic_key_omitted_from_payload_when_none(tmp_path, capsys):
    post = Poster()
    run(tmp_path, capsys, post=post)
    for it in post.calls[0][1]["items"]:
        assert "epic_key" not in it
