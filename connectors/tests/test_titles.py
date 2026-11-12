import pytest

from loopboard_connectors.contract import split_epic_prefix


@pytest.mark.parametrize("title,key,rest", [
    ("[DEMO-E5] Add checkout retry", "DEMO-E5", "Add checkout retry"),
    ("[DEMO-E5]Add checkout retry", "DEMO-E5", "Add checkout retry"),
    ("\t [X1-E0]  y", "X1-E0", "y"),
    ("[ABCDEFGHIJ-E123] long project key", "ABCDEFGHIJ-E123", "long project key"),
])
def test_title_prefix_sets_epic_key_and_strips_title(title, key, rest):
    assert split_epic_prefix(title) == (key, rest)


@pytest.mark.parametrize("title", [
    "Add checkout retry [DEMO-E5]",
    "Fix [DEMO-E5] Add checkout retry",
    "fix: [DEMO-E5] retry",
])
def test_prefix_only_at_start(title):
    assert split_epic_prefix(title) == (None, title)


@pytest.mark.parametrize("title", [
    "[demo-e5] lowercase",
    "[Demo-E5] mixed case",
    "[DEMO-e5] lowercase e",
    "[DEMO-E] no number",
    "[DEMO5] no epic part",
    "[D-E5] project key too short",
    "[ABCDEFGHIJK-E5] project key too long",
    "[1DEMO-E5] starts with a digit",
    "[DEMO-E5 ] space inside",
    "(DEMO-E5) wrong brackets",
    "[DEMO-E5]",
    "",
])
def test_malformed_or_lowercase_prefix_ignored(title):
    assert split_epic_prefix(title) == (None, title)
