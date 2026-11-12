import pytest

from loopboard.model import ValidationError, parse_ts


def test_parse_ts_offset_to_utc():
    assert parse_ts("2026-11-12T09:00:00+07:00") == parse_ts("2026-11-12T02:00:00Z")


def test_parse_ts_naive_rejected():
    with pytest.raises(ValidationError):
        parse_ts("2026-11-12T09:00:00")


def test_parse_ts_garbage_rejected():
    with pytest.raises(ValidationError):
        parse_ts("not a time")


def test_parse_ts_out_of_range_rejected():
    import pytest

    from loopboard.model import ValidationError, parse_ts

    for s in ("9999-12-31T23:59:59-14:00", "0001-01-01T00:00:00+14:00"):
        with pytest.raises(ValidationError):
            parse_ts(s)


def test_item_url_must_be_http_or_https():
    from pydantic import ValidationError as PydanticError

    from loopboard.model import ItemIn

    base = dict(external_id="1", title="t", status_category="done", last_activity_at="2026-11-12T00:00:00Z")
    assert ItemIn(**base, url="https://example.com/x").url == "https://example.com/x"
    for bad in ("data:text/html,x", "javascript:alert(1)", "example.com"):
        with pytest.raises(PydanticError):
            ItemIn(**base, url=bad)
