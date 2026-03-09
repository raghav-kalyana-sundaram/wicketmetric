from pathlib import Path

from cricwarehouse.app.parse import parse_match_file

ROOT = Path(__file__).resolve().parents[1]


def test_dls_match_flagged_when_present():
    path = ROOT / "ipl_json-1" / "1370353.json"
    if not path.exists():
        return
    parsed = parse_match_file(path, readme_code="IPL")
    assert parsed is not None
    assert parsed["match"]["result_method"] == "dls"
    assert parsed["match"]["revised_target"] == 171
    assert parsed["match"]["revised_overs"] == 15


def test_super_over_excluded_from_regular_innings():
    path = ROOT / "ipl_json-1" / "1473469.json"
    if not path.exists():
        return
    parsed = parse_match_file(path, readme_code="IPL")
    assert parsed is not None
    assert parsed["match"]["result_method"] == "super_over"
    kinds = {d["innings_kind"] for d in parsed["deliveries"]}
    assert "regular" in kinds
    assert "super_over" in kinds
    assert all(d["innings_kind"] == "regular" or d["innings"] >= 100 for d in parsed["deliveries"])
