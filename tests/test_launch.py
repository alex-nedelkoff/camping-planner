"""Tests for launch.py helpers."""

import pytest

from launch import replace_first_table, _md_escape_cell


GEAR_MD = """## Shared gear

| Item | Who's bringing | Notes |
|---|---|---|
| Canoe | TBD | rental? |
| Paddles | Alex | |

## Personal gear

Each person brings their own.
"""


def test_replace_first_table_replaces_only_data_rows():
    new = replace_first_table(GEAR_MD, [["Stove", "Jordan", "white gas"]])
    assert "| Stove | Jordan | white gas |" in new
    # Header preserved
    assert "| Item | Who's bringing | Notes |" in new
    # Old rows gone
    assert "Canoe" not in new
    assert "Paddles" not in new
    # Trailing section preserved
    assert "## Personal gear" in new


def test_replace_first_table_pads_short_rows():
    new = replace_first_table(GEAR_MD, [["Tarp"]])
    assert "| Tarp |  |  |" in new


def test_replace_first_table_truncates_extra_columns():
    new = replace_first_table(GEAR_MD, [["a", "b", "c", "d", "e"]])
    assert "| a | b | c |" in new
    assert "| d |" not in new


def test_replace_first_table_empty_rows_keeps_header():
    new = replace_first_table(GEAR_MD, [])
    assert "| Item | Who's bringing | Notes |" in new
    assert "Canoe" not in new
    assert "## Personal gear" in new


def test_replace_first_table_escapes_pipes_and_newlines():
    new = replace_first_table(GEAR_MD, [["a|b", "two\nlines", "ok"]])
    assert r"a\|b" in new
    assert "two lines" in new


def test_replace_first_table_raises_when_no_table():
    with pytest.raises(ValueError, match="no markdown table"):
        replace_first_table("# Just text\n\nNo table here.\n", [["x"]])


def test_md_escape_cell_handles_backslash():
    assert _md_escape_cell("a\\b") == "a\\\\b"
