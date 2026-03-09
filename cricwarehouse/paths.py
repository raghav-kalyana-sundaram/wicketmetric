from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CRICSHEET = DATA / "cricsheet"
WAREHOUSE = DATA / "warehouse"
PERSONAL = DATA / "personal"
USER_DATA = ROOT / "user_data"
UI = ROOT / "ui"
LOCAL_DUMPS = (
    ROOT / "ipl_json-1",
    ROOT / "ipl_json",
    ROOT / "bbl_json",
    ROOT / "wpl_json",
    ROOT / "wbbl_json",
    ROOT / "all_male_json",
    ROOT / "all_female_json",
    CRICSHEET / "ipl_json",
    CRICSHEET / "bbl_json",
    CRICSHEET / "wpl_json",
    CRICSHEET / "wbbl_json",
    CRICSHEET / "t20s_male_json",
    CRICSHEET / "t20s_female_json",
    CRICSHEET / "tests_male_json",
    CRICSHEET / "tests_female_json",
    CRICSHEET / "all_male_json",
    CRICSHEET / "all_female_json",
)


def ensure_dirs() -> None:
    for path in (DATA, CRICSHEET, WAREHOUSE, PERSONAL, USER_DATA):
        path.mkdir(parents=True, exist_ok=True)
