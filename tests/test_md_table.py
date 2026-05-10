"""Tests for the markdown-table helpers used by /api/save-gear."""

import pytest

from app.services.trips import (
    _md_escape_cell,
    _parse_amount,
    costs_summary_html,
    replace_first_table,
)


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


# ---------------------------------------------------------------------------
# Costs auto-summary
# ---------------------------------------------------------------------------


COSTS_MD = """| Item | Who paid | Amount ($) |
|---|---|---|
| Permit | Alex | 99 |
| Gas | Jordan | 400 |
| Groceries | Alex | 122 |
"""


def test_parse_amount_strips_dollar_and_commas():
    assert _parse_amount("$1,234.56") == 1234.56
    assert _parse_amount("  42 ") == 42.0
    assert _parse_amount("") is None
    assert _parse_amount("n/a") is None


def test_costs_summary_splits_total_across_participants():
    html = costs_summary_html(COSTS_MD, participant_count=3)
    # 99 + 400 + 122 = 621; / 3 = 207.00
    assert "$621.00" in html
    assert "$207.00" in html
    assert "Per person (3)" in html


def test_costs_summary_handles_currency_formatted_cells():
    md = (
        "| Item | Who paid | Amount ($) |\n"
        "|---|---|---|\n"
        "| Permit | Alex | $99.00 |\n"
        "| Gas | Jordan | $1,000 |\n"
    )
    html = costs_summary_html(md, participant_count=2)
    assert "$1,099.00" in html
    assert "$549.50" in html


def test_costs_summary_blank_when_no_amounts():
    md = (
        "| Item | Who paid | Amount ($) |\n"
        "|---|---|---|\n"
        "| Permit | | |\n"
    )
    assert costs_summary_html(md, participant_count=2) == ""


def test_costs_summary_no_participants_warns():
    html = costs_summary_html(COSTS_MD, participant_count=0)
    assert "$621.00" in html
    assert "add participants" in html


def test_costs_summary_legacy_amount_header_still_works():
    """Old trips that haven't migrated still parse — header is matched fuzzily."""
    md = (
        "| Item | Who paid | Amount |\n"
        "|---|---|---|\n"
        "| Permit | Alex | 50 |\n"
    )
    html = costs_summary_html(md, participant_count=2)
    assert "$50.00" in html
    assert "$25.00" in html
