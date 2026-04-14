from cricwarehouse.app.db import venue_map


def canonical(pairs):
    return {raw: name for raw, (name, _city) in venue_map(pairs).items()}


def test_bare_and_city_suffixed_names_collapse():
    """Cricsheet writes the same ground both ways depending on file vintage."""
    names = canonical([("Lord's", "London"), ("Lord's, London", "London")])
    assert names[("Lord's", "London")] == "Lord's, London"
    assert names[("Lord's, London", "London")] == "Lord's, London"


def test_same_ground_name_in_different_cities_stays_apart():
    names = canonical([("County Ground", "Bristol"), ("County Ground", "Derby")])
    assert names[("County Ground", "Bristol")] == "County Ground, Bristol"
    assert names[("County Ground", "Derby")] == "County Ground, Derby"


def test_renamed_city_and_stale_district_collapse():
    names = canonical(
        [
            ("Shere Bangla National Stadium", "Dhaka"),
            ("Shere Bangla National Stadium, Mirpur", "Mirpur"),
        ]
    )
    assert set(names.values()) == {"Shere Bangla National Stadium, Dhaka"}


def test_missing_space_after_initial_is_repaired():
    names = canonical(
        [
            ("M Chinnaswamy Stadium", "Bangalore"),
            ("M.Chinnaswamy Stadium", "Bengaluru"),
        ]
    )
    assert set(names.values()) == {"M Chinnaswamy Stadium, Bangalore"}


def test_city_backfilled_from_other_matches_at_same_ground():
    names = canonical(
        [
            ("Dubai International Cricket Stadium", "Dubai"),
            ("Dubai International Cricket Stadium", None),
        ]
    )
    assert set(names.values()) == {"Dubai International Cricket Stadium, Dubai"}


def test_ground_without_any_known_city_is_left_alone():
    names = canonical([("Some Oval", None)])
    assert names[("Some Oval", "")] == "Some Oval"
