"""Stats table can sort by form overall when the warehouse is built."""

from __future__ import annotations

import pytest

from cricwarehouse.app.db import warehouse_ready
from cricwarehouse.app.form import form_ready


pytestmark = pytest.mark.skipif(
    not warehouse_ready() or not form_ready(),
    reason="Warehouse and form ratings are required",
)


def test_stats_sort_by_form_overall_is_descending():
    from cricwarehouse.app.catalog import master_stats

    data = master_stats(comp="t20i_ipl", gender="male", min_inns=8, role="all", sort="form")
    rated = [r for r in data["rows"] if r.get("form") is not None]
    assert rated
    forms = [int(r["form"]) for r in rated]
    assert forms == sorted(forms, reverse=True)
    assert forms[0] >= 80
    aliases = master_stats(comp="t20i_ipl", gender="male", min_inns=8, role="all", sort="overall")
    assert (aliases["rows"] or [{}])[0].get("person_id") == rated[0].get("person_id")
