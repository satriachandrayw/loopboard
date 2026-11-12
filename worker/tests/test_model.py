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
