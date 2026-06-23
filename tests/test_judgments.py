"""Warehouse integration for the 50 Test-rating judgments."""

from __future__ import annotations

import pytest

from cricwarehouse.app.test_value import ratings_ready


@pytest.mark.skipif(not ratings_ready(), reason="test ratings not built")
def test_judgment_harness_runs():
    from cricwarehouse.app.judgments import run_judgments

    report = run_judgments()
    assert report["ok"]
    assert report["weight"] > 0
    # Hard constraints must not be skipped when ratings exist.
    hard_skips = [s["n"] for s in report["skips"] if s["n"] in {1, 3, 9, 21, 36, 39, 45, 49}]
    assert hard_skips == [] or set(hard_skips) <= {40}
