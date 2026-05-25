import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "compile_site_survey.py"
spec = importlib.util.spec_from_file_location("compile_site_survey", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_compile_resolves_enums_buckets_photos():
    attr_defs = {
        -32762: {"name": "Privacy", "values": {0: "Poor", 1: "Average", 2: "Good"}},
        -32743: {"name": "Site Length (m)", "values": {}},
    }
    resources = {
        "1": {
            "resourceId": 1,
            "localizedValues": [
                {"name": "312", "description": "nice", "cultureName": "en-CA"}
            ],
            "mapIds": [10],
            "maxCapacity": 6,
            "allowedEquipment": [1, 2, 3, 4, 5],
            "definedAttributes": [
                {"attributeDefinitionId": -32762, "value": None, "values": [2]},
                {"attributeDefinitionId": -32743, "value": 20.0, "values": []},
            ],
            "photos": [{"photoUrlResult": {"url": "https://x/1.jpg"}}],
        }
    }
    survey = mod.compile_survey(resources, attr_defs, "test-park", "Test Park", "2026-05-24")
    assert survey["park_slug"] == "test-park"
    assert survey["park_name"] == "Test Park"
    assert survey["pulled_on"] == "2026-05-24"
    assert survey["site_count"] == 1
    site = survey["sites"][0]
    assert site["name"] == "312"
    assert site["description"] == "nice"
    assert site["max_capacity"] == 6
    assert site["attributes"]["Privacy"] == "Good"
    assert site["attributes"]["Site Length (m)"] == 20.0
    assert site["equipment_bucket"] == "Trailer / motorhome"
    assert site["photos"] == ["https://x/1.jpg"]
    assert site["campground"].startswith("Sites #312")


def test_load_attr_defs_reads_enum_labels(tmp_path):
    catalog = tmp_path / "cat.json"
    catalog.write_text(
        '{"a": {"attributeDefinitionId": -32762,'
        ' "localizedValues": [{"cultureName": "en-CA", "displayName": "Privacy"}],'
        ' "values": [{"enumValue": 2,'
        '   "localizedValues": [{"cultureName": "en-CA", "displayName": "Good"}]}]}}'
    )
    defs = mod.load_attr_defs(catalog)
    assert defs[-32762]["name"] == "Privacy"
    assert defs[-32762]["values"][2] == "Good"
