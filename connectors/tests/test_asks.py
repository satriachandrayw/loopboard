import json

import pytest

from loopboard_connectors import asks, cli
from loopboard_connectors.contract import Item, SourceError

TOKEN = "lb_supersecrettoken"
HOW = "Reply to your agent in chat with the code and your answer."
PROJECTS = {"demo app": "DEMO", "Sample_Tool": "SAMPLE"}


def a(**over):
    d = {"code": "D-1", "question": "Ship the demo on Friday?", "project": "demo app", "status": "open",
         "updated_at": 1763700000, "url": None}
    d.update(over)
    return d


def m(ask=None, **kw):
    kw.setdefault("source", "asks")
    kw.setdefault("human", "owner")
    kw.setdefault("projects", PROJECTS)
    kw.setdefault("default_project", "INBOX")
    return asks.map_ask(ask or a(), **kw)


# --- mapping ---

def test_open_ask_maps_to_a_todo_item_waiting_on_the_human():
    i = m()
    assert i == Item(source="asks", external_id="D-1", title="Ship the demo on Friday?", url=None,
                     status_category="todo", raw_status="open", owner=None, waiting_on="human:owner",
                     blocked_reason=None, next_step=None, project_key="DEMO", epic_key=None,
                     last_activity_at="2025-11-21T04:40:00Z", question="Ship the demo on Friday?",
                     answer_how=HOW, reply_code="D-1")


@pytest.mark.parametrize("status", ["answered", "resolved", "expired", "dropped"])
def test_closed_statuses_map_to_done_waiting_on_nobody(status):
    i = m(a(status=status))
    assert (i.status_category, i.raw_status, i.waiting_on) == ("done", status, None)
    assert (i.question, i.reply_code) == ("Ship the demo on Friday?", "D-1")


def test_source_and_url_come_through():
    i = m(a(url="https://example.test/thread/1"), source="assistant")
    assert (i.source, i.url) == ("assistant", "https://example.test/thread/1")
    assert m({k: v for k, v in a().items() if k != "url"}).url is None


@pytest.mark.parametrize("name,key", [
    ("demo app", "DEMO"), ("DemoApp", "DEMO"), ("demo-app", "DEMO"), ("demo_app", "DEMO"),
    (" Demo  App ", "DEMO"), ("sample tool", "SAMPLE"), ("sample-tool", "SAMPLE"),
    ("unknown", "INBOX"), ("", "INBOX"), ("   ", "INBOX"), (None, "INBOX")])
def test_project_names_are_normalised_and_fall_back_to_default(name, key):
    assert m(a(project=name)).project_key == key


def test_long_question_is_cut_to_300_for_title_and_question():
    i = m(a(question="x" * 450))
    assert i.title == i.question == "x" * 300


def test_question_is_stripped():
    assert m(a(question="  Ship it?  ")).question == "Ship it?"


@pytest.mark.parametrize("bad", [
    {"code": None}, {"code": ""}, {"code": 12}, {"code": "D" * 41},
    {"question": None}, {"question": "  "}, {"question": 3},
    {"project": 7},
    {"status": "pending"}, {"status": None},
    {"updated_at": "1763700000"}, {"updated_at": True}, {"updated_at": None}, {"updated_at": -1},
    {"url": "ftp://example.test/x"}, {"url": 5}, {"url": "javascript:alert(1)"},
])
def test_malformed_fields_fail(bad):
    with pytest.raises(SourceError):
        m(a(**bad))


@pytest.mark.parametrize("field", ["code", "question", "project", "status", "updated_at"])
def test_missing_field_fails(field):
    d = a()
    del d[field]
    with pytest.raises(SourceError, match=field):
        m(d)


def test_float_epoch_is_accepted():
    assert m(a(updated_at=1763700000.9)).last_activity_at == "2025-11-21T04:40:00Z"


# --- file ---

def write(tmp_path, data, name="asks.json"):
    p = tmp_path / name
    p.write_text(data if isinstance(data, str) else json.dumps(data))
    return p


def test_collect_reads_every_ask(tmp_path):
    p = write(tmp_path, {"asks": [a(), a(code="D-2", status="resolved")]})
    items = asks.collect(p, source="asks", human="owner", projects=PROJECTS, default_project="INBOX")
    assert [(i.external_id, i.status_category) for i in items] == [("D-1", "todo"), ("D-2", "done")]


@pytest.mark.parametrize("data", ["{not json", "[]", '{"asks": {}}', "{}", '{"asks": [1]}', '"x"'])
def test_bad_file_shape_fails(tmp_path, data):
    with pytest.raises(SourceError):
        asks.collect(write(tmp_path, data), source="asks", human="owner", projects={}, default_project="INBOX")


def test_missing_file_fails(tmp_path):
    with pytest.raises(SourceError):
        asks.collect(tmp_path / "nope.json", source="asks", human="owner", projects={}, default_project="INBOX")


def test_collect_never_writes_the_file(tmp_path):
    p = write(tmp_path, {"asks": [a()]})
    before = (p.read_bytes(), p.stat().st_mtime_ns)
    asks.collect(p, source="asks", human="owner", projects=PROJECTS, default_project="INBOX")
    assert (p.read_bytes(), p.stat().st_mtime_ns) == before


# --- payload ---

def test_payload_carries_ask_fields():
    d = m().to_payload()
    assert (d["question"], d["answer_how"], d["reply_code"]) == ("Ship the demo on Friday?", HOW, "D-1")
    assert "source" not in d and "epic_key" not in d and "task_key" not in d


def test_payload_omits_ask_fields_for_other_connectors():
    base = dict(source="kanban", external_id="1", title="t", url=None, status_category="todo", raw_status="todo",
                owner=None, waiting_on="agent:a", blocked_reason=None, next_step=None, project_key="DEMO",
                epic_key=None, last_activity_at="2026-11-12T00:00:00Z")
    d = Item(**base).to_payload()
    assert set(d) == {"external_id", "title", "url", "status_category", "raw_status", "owner", "waiting_on",
                      "blocked_reason", "next_step", "project_key", "last_activity_at", "merged_at", "live_at"}


# --- CLI ---

def cfg(tmp_path, asks_file, extra=""):
    p = tmp_path / "config.toml"
    p.write_text('[loopboard]\nurl = "https://lb.example.test/"\ntoken_env = "LB_TOKEN"\n'
                 '[general]\nhuman = "owner"\n'
                 f'[asks]\nfile = "{asks_file}"\ndefault_project = "INBOX"\n{extra}'
                 '[asks.projects]\n"demo app" = "DEMO"\n')
    return p


class Poster:
    def __init__(self):
        self.calls = []

    def __call__(self, url, body, headers):
        payload = json.loads(body)
        self.calls.append((url, payload, headers))
        n = len(payload["items"])
        return {"accepted": n, "created": n, "ask_tasks": n}


def run(tmp_path, capsys, data, *extra, env=None, post=None, config_extra="", asks_file=None):
    f = asks_file or write(tmp_path, data)
    argv = ["sync", "asks", "--config", str(cfg(tmp_path, f, config_extra)), *extra]
    code = cli.main(argv, env={"LB_TOKEN": TOKEN} if env is None else env, post=post)
    out = capsys.readouterr()
    return code, json.loads(out.out.strip().splitlines()[-1])


def test_cli_posts_asks(tmp_path, capsys):
    post = Poster()
    code, s = run(tmp_path, capsys, {"asks": [a(), a(code="D-2", project="nowhere", status="dropped")]}, post=post)
    assert code == 0
    assert (s["connector"], s["collected"], s["accepted"], s["ask_tasks"], s["posts"], s["dry_run"]) == (
        "asks", 2, 2, 2, 1, False)
    url, payload, headers = post.calls[0]
    assert url == "https://lb.example.test/api/ingest" and headers["Authorization"] == f"Bearer {TOKEN}"
    assert payload["source"] == "asks"
    assert [(i["external_id"], i["project_key"]) for i in payload["items"]] == [("D-1", "DEMO"), ("D-2", "INBOX")]


def test_cli_source_comes_from_config(tmp_path, capsys):
    post = Poster()
    code, s = run(tmp_path, capsys, {"asks": [a()]}, post=post, config_extra='source = "assistant"\n')
    assert code == 0 and post.calls[0][1]["source"] == "assistant"


def test_cli_batches_by_100(tmp_path, capsys):
    post = Poster()
    code, s = run(tmp_path, capsys, {"asks": [a(code=f"D-{n}") for n in range(1, 251)]}, post=post)
    assert code == 0 and [len(c[1]["items"]) for c in post.calls] == [100, 100, 50]
    assert (s["collected"], s["posts"]) == (250, 3)


def test_cli_dry_run_posts_nothing_and_needs_no_token(tmp_path, capsys):
    post = Poster()
    code, s = run(tmp_path, capsys, {"asks": [a()]}, "--dry-run", env={}, post=post)
    assert code == 0 and post.calls == [] and (s["collected"], s["posts"], s["dry_run"]) == (1, 0, True)


def test_cli_malformed_file_posts_nothing(tmp_path, capsys):
    post = Poster()
    code, s = run(tmp_path, capsys, {"asks": [a(), a(code="D-2", status="maybe")]}, post=post)
    assert code == 1 and post.calls == [] and s["connector"] == "asks" and "error" in s


def test_cli_missing_token_is_a_config_error(tmp_path, capsys):
    code, s = run(tmp_path, capsys, {"asks": [a()]}, env={}, post=Poster())
    assert code == 2 and "error" in s


@pytest.mark.parametrize("extra,bad", [
    ("", 'default_project = "INBOX"\n'),
    ("", 'file = "'),
    ('source = "Bad Source"\n', None),
])
def test_cli_config_errors(tmp_path, capsys, extra, bad):
    f = write(tmp_path, {"asks": [a()]})
    p = cfg(tmp_path, f, extra)
    if bad is not None:
        text = p.read_text()
        start = text.index(bad)
        p.write_text(text[:start] + text[text.index("\n", start) + 1:])
    code = cli.main(["sync", "asks", "--config", str(p)], env={"LB_TOKEN": TOKEN}, post=Poster())
    s = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 2 and "error" in s


def test_cli_relative_file_is_relative_to_the_config(tmp_path, capsys):
    write(tmp_path, {"asks": [a()]})
    post = Poster()
    code, s = run(tmp_path, capsys, None, post=post, asks_file="asks.json")
    assert code == 0 and s["collected"] == 1


def test_cli_rejected_ingest(tmp_path, capsys):
    from loopboard_connectors.contract import IngestRejected

    def post(url, body, headers):
        raise IngestRejected(422, "nope")
    code, s = run(tmp_path, capsys, {"asks": [a()]}, post=post)
    assert code == 3 and "422" in s["error"]
