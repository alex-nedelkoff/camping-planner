from app.services.site_surveys import find_site

SURVEY = {"sites": [
    {"name": "123", "campground": "A"},
    {"name": "Site 7", "campground": "B"},
]}


def test_exact_number():
    assert find_site(SURVEY, "123")["campground"] == "A"


def test_with_site_prefix_and_case():
    assert find_site(SURVEY, "site 123")["campground"] == "A"
    assert find_site(SURVEY, "  7 ")["campground"] == "B"
    assert find_site(SURVEY, "SITE 7")["campground"] == "B"


def test_blank_or_missing_returns_none():
    assert find_site(SURVEY, "") is None
    assert find_site(SURVEY, "999") is None
    assert find_site(None, "123") is None
