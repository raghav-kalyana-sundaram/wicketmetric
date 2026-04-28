from __future__ import annotations

import pytest

from cricwarehouse.paths import ROOT

FIXTURE_IDS = ("335985", "335986", "335987")


@pytest.fixture(scope="session")
def ipl_2008_paths() -> list:
    """The three attached IPL 2008 fixtures, if the local Cricsheet dump is present."""
    dump = ROOT / "ipl_json-1"
    paths = [dump / f"{mid}.json" for mid in FIXTURE_IDS]
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"IPL dump not present locally: {', '.join(missing)}")
    return paths
