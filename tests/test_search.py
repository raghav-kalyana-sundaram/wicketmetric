from cricwarehouse.app.search import SearchIndex, is_known_team, lift_bare


def test_team_aliases():
    assert is_known_team("New Zealand") == "New Zealand"
    assert is_known_team("nz") == "New Zealand"
    assert is_known_team("kiwis") == "New Zealand"
    assert is_known_team("rcb") == "Royal Challengers Bengaluru"
    assert is_known_team("kohli") is None


def test_lift_sachin_nz_94():
    lifted = lift_bare("Sachin Tendulkar New Zealand 94")
    assert lifted.player == "Sachin Tendulkar"
    assert lifted.tokens.get("side") == "New Zealand"
    assert lifted.tokens["runs"] == "94"


def test_people_index_token_and():
    idx = SearchIndex.from_rows(
        [
            {
                "person_id": "tendulkar",
                "display_name": "SR Tendulkar",
                "unique_name": "SR Tendulkar",
                "slug": "sr-tendulkar",
                "name_variants": "Sachin Tendulkar",
                "apps": 600,
            },
            {
                "person_id": "other",
                "display_name": "Sachin Baby",
                "unique_name": "Sachin Baby",
                "slug": "sachin-baby",
                "apps": 20,
            },
            {
                "person_id": "smith",
                "display_name": "SPD Smith",
                "unique_name": "SPD Smith",
                "slug": "spd-smith",
                "apps": 200,
            },
        ]
    )
    hits = idx.search("sachin tendulkar")
    assert hits[0]["person_id"] == "tendulkar"
    last = idx.search("tendulkar")
    assert last[0]["person_id"] == "tendulkar"
    smith = idx.search("smith")
    assert smith[0]["person_id"] == "smith"
