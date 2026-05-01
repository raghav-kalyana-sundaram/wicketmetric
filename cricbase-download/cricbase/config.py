from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw" / "cricsheet"
DB_PATH = DATA_DIR / "db" / "cricbase.sqlite"
PEOPLE_CSV = ROOT / "people.csv"

CRICSHEET_DOWNLOADS = {
    "Test": "https://cricsheet.org/downloads/tests_json.zip",
    "ODI": "https://cricsheet.org/downloads/odis_json.zip",
}

# ICC full members. Matches are kept when both sides are in this set.
TEST_NATIONS = frozenset(
    {
        "Afghanistan",
        "Australia",
        "Bangladesh",
        "England",
        "ICC World XI",
        "India",
        "Ireland",
        "New Zealand",
        "Pakistan",
        "South Africa",
        "Sri Lanka",
        "West Indies",
        "Zimbabwe",
    }
)

# ODIs also keep regular associate and invitational sides so World Cups aren't gapped.
ODI_NATIONS = TEST_NATIONS | frozenset(
    {
        "Africa XI",
        "Asia XI",
        "Bermuda",
        "Canada",
        "Hong Kong",
        "Kenya",
        "Namibia",
        "Nepal",
        "Netherlands",
        "Oman",
        "Papua New Guinea",
        "Scotland",
        "United Arab Emirates",
        "United States of America",
        "USA",
    }
)

MATCH_TYPES = frozenset({"Test", "ODI"})
DEFAULT_GENDER = "male"
