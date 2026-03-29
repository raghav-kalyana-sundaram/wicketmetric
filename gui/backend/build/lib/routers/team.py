"""
Team Builder router — /api/team endpoints.

Provides:
- GET /api/team/analyse   → Aggregate team analysis for a set of player IDs
- GET /api/team/auto-fill → Suggested XI based on a strategy (war, power, control, country)

These endpoints support the Team Builder page (gui.md § 6.8), which lets
users assemble hypothetical T20I XIs and see aggregate team metrics,
a team radar chart, and weakness detection.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from rating_display import batting_display_ratings, bowling_display_ratings
from schemas import PlayerSummary, TeamAnalysis

if TYPE_CHECKING:
    import pandas as pd
    from data_loader import DataStore

router = APIRouter(prefix="/api", tags=["team"])


# ── Dependency placeholder (overridden in app.py) ─────────────────


def _get_store():
    raise RuntimeError("DataStore not initialised")


# ── Helpers ───────────────────────────────────────────────────────


def _safe_float(v: Any) -> float | None:
    """Convert to float, returning None for NaN/inf."""
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 2)
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    s = str(v)
    if s in ("nan", "NaN", "None", "<NA>", "NaT"):
        return default
    return s


def _normalise_phase_group(raw: Any) -> str | None:
    s = _safe_str(raw, "").strip().lower()
    if not s or s in ("unknown", "nan", "none"):
        return None
    return s


def _row_to_player_summary(
    row: Any,
    role: str,
    *,
    phase_group: str | None = None,
    allrounder_class: str | None = None,
) -> PlayerSummary:
    """Convert a pandas Series (career row) to a PlayerSummary."""
    if role == "bat":
        rating_overall, rating_current = batting_display_ratings(row)
        mp = _safe_int(row.get("modal_position"))
        modal_position = mp if mp is not None and 1 <= mp <= 11 else None
        return PlayerSummary(
            id=_safe_str(row.get("batter_id"), ""),
            name=_safe_str(row.get("batter"), "Unknown"),
            country=_safe_str(row.get("country"), ""),
            role="bat",
            archetype=_safe_str(row.get("archetype"), ""),
            grade_overall=_safe_str(row.get("overall_grade"), "D"),
            innings_count=_safe_int(row.get("innings_count")) or 0,
            total_runs=_safe_int(row.get("total_runs")) or 0,
            career_sr=_safe_float(row.get("career_sr")),
            career_avg=_safe_float(row.get("career_avg")),
            score_1=_safe_float(row.get("score_acceleration")),
            score_2=_safe_float(row.get("score_power")),
            score_3=_safe_float(row.get("score_control")),
            score_1_label="acceleration",
            score_2_label="power",
            score_3_label="control",
            is_provisional=bool(row.get("is_provisional_bat", True)),
            overall_score=_safe_float(row.get("overall_score"))
            or _safe_float(row.get("composite_batting")),
            rating_current=rating_current,
            rating_overall=rating_overall,
            modal_position=modal_position,
            recent_team=(
                _safe_str(row.get("recent_team"), "").strip() or None
                if hasattr(row, "get")
                else (
                    _safe_str(getattr(row, "recent_team", None), "").strip() or None
                )
            ),
            phase_group=None,
            allrounder_class=allrounder_class,
        )
    else:
        rating_overall, rating_current = bowling_display_ratings(row)
        pg = phase_group if phase_group is not None else _normalise_phase_group(
            row.get("phase_group")
        )
        return PlayerSummary(
            id=_safe_str(row.get("bowler_id"), ""),
            name=_safe_str(row.get("bowler"), "Unknown"),
            country=_safe_str(row.get("country"), ""),
            role="bowl",
            archetype=_safe_str(row.get("archetype"), ""),
            grade_overall=_safe_str(row.get("overall_grade"), "D"),
            innings_count=_safe_int(row.get("matches")) or 0,
            total_runs=_safe_int(row.get("total_wickets")) or 0,
            career_sr=_safe_float(row.get("career_economy")),
            career_avg=None,
            score_1=_safe_float(row.get("score_accuracy")),
            score_2=_safe_float(row.get("score_control")),
            score_3=_safe_float(row.get("score_threat")),
            score_1_label="accuracy",
            score_2_label="control",
            score_3_label="threat",
            is_provisional=bool(row.get("is_provisional_bowl", True)),
            overall_score=_safe_float(row.get("overall_score"))
            or _safe_float(row.get("composite_bowling")),
            rating_current=rating_current,
            rating_overall=rating_overall,
            modal_position=None,
            recent_team=(
                _safe_str(row.get("recent_team"), "").strip() or None
                if hasattr(row, "get")
                else (
                    _safe_str(getattr(row, "recent_team", None), "").strip() or None
                )
            ),
            phase_group=pg,
            allrounder_class=allrounder_class,
        )


# ── Archetype-based role classification ───────────────────────────
#
# The pipeline assigns archetypes from two disjoint lists: batting
# archetypes (in bat_careers) and bowling archetypes (in bowl_careers).
# These are the authoritative signal for whether a player is a batter
# or a bowler.  The sets below list every known archetype label so we
# can classify without fragile ratio heuristics.
#
# If a new archetype is added to presentation.py it should be added
# here too; the "Unknown" / "Utility Player" fallback archetypes are
# deliberately omitted so the code falls through to the secondary
# heuristic for unrecognised labels.

_BATTING_ARCHETYPES = {
    "Explosive Finisher",
    "Explosive Opener",
    "Power Hitter",
    "Pinch Hitter",
    "Aggressive Opener",
    "Power Middle-Order",
    "Classic Anchor",
    "Power Anchor",
    "All-Round Elite",
    "Strike Rotator",
    "Accumulator",
    "Float",
}

_BOWLING_ARCHETYPES = {
    "Death Specialist",
    "Powerplay Enforcer",
    "Strike Bowler",
    "Spin Restrictor",
    "Economical",
    "All-Round Threat",
    "Restrictive Spinner",
    "Enforcer",
}


def _is_genuine_bowler(bowl_row: dict, store: Any) -> bool:
    """Determine if a player is a genuine bowler.

    Classification priority:
    1. **Archetype label** — if the player's bowling archetype is in the
       known ``_BOWLING_ARCHETYPES`` set, they are a genuine bowler.
       If instead their archetype is a known *batting* label (which can
       happen for players who appear in both datasets), they are NOT a
       genuine bowler.
    2. **Fallback heuristic** — for unknown / missing archetypes, require
       at least 10 bowling matches AND a bowl-match / bat-innings ratio
       ≥ 0.40 (stricter than the old 0.25 threshold).
    """
    # ── 1. Archetype-based check (primary) ────────────────────
    archetype = str(bowl_row.get("archetype", "") or "").strip()
    if archetype in _BOWLING_ARCHETYPES:
        return True
    if archetype in _BATTING_ARCHETYPES:
        # Explicitly a batter's archetype — not a genuine bowler
        return False

    # ── 2. Fallback heuristic for unknown/missing archetypes ──
    bowl_matches = float(bowl_row.get("matches", 0) or 0)

    # Must have minimum bowling sample
    if bowl_matches < 10:
        return False

    # Cross-reference with batting careers
    bowler_id = str(bowl_row.get("bowler_id", ""))
    if (
        not bowler_id
        or store.bat_careers.empty
        or "batter_id" not in store.bat_careers.columns
    ):
        return True  # No batting data available → treat as pure bowler

    bat_mask = store.bat_careers["batter_id"] == bowler_id
    bat_matches = store.bat_careers.loc[bat_mask]

    if bat_matches.empty:
        return True  # No batting record → pure bowler

    bat_innings = float(bat_matches.iloc[0].get("innings_count", 0) or 0)
    if bat_innings <= 0:
        return True

    ratio = bowl_matches / bat_innings
    return ratio >= 0.40


def _is_genuine_batter(bat_row: dict, store: Any) -> bool:
    """Determine if a player contributes meaningfully with the bat.

    Classification priority:
    1. **Archetype label** — if the player's batting archetype is in the
       known ``_BATTING_ARCHETYPES`` set, they are a genuine batter.
       If instead their archetype is a known *bowling* label, they are
       NOT a genuine batter.
    2. **Fallback heuristic** — for unknown / missing archetypes, require
       at least 10 batting innings AND a composite batting score ≥ 20.
    """
    # ── 1. Archetype-based check (primary) ────────────────────
    archetype = str(bat_row.get("archetype", "") or "").strip()
    if archetype in _BATTING_ARCHETYPES:
        return True
    if archetype in _BOWLING_ARCHETYPES:
        # Explicitly a bowler's archetype — not a genuine batter
        return False

    # ── 2. Fallback heuristic for unknown/missing archetypes ──
    innings = float(bat_row.get("innings_count", 0) or 0)
    if innings < 10:
        return False

    composite = bat_row.get("overall_score") or bat_row.get("composite_batting")
    if composite is not None:
        try:
            if float(composite) < 20:
                return False
        except (TypeError, ValueError):
            pass

    return True


def _get_genuine_bowlers_df(store: Any) -> "pd.DataFrame":
    """Return a filtered copy of store.bowl_careers containing only genuine bowlers."""
    import pandas as pd

    if store.bowl_careers.empty:
        return pd.DataFrame()

    mask = store.bowl_careers.apply(
        lambda row: _is_genuine_bowler(row.to_dict(), store), axis=1
    )
    return store.bowl_careers.loc[mask]


def _get_genuine_batters_df(store: Any) -> "pd.DataFrame":
    """Return a filtered copy of store.bat_careers containing only genuine batters."""
    import pandas as pd

    if store.bat_careers.empty:
        return pd.DataFrame()

    mask = store.bat_careers.apply(
        lambda row: _is_genuine_batter(row.to_dict(), store), axis=1
    )
    return store.bat_careers.loc[mask]


_DEFAULT_SLOT_SEQUENCE = (
    "opener",
    "opener",
    "top_order",
    "top_order",
    "middle_order",
    "middle_order",
    "finisher_wk",
    "allrounder",
    "bowler",
    "bowler",
    "bowler",
)

_VALID_SLOT_TYPES = frozenset(
    {
        "opener",
        "top_order",
        "middle_order",
        "finisher_wk",
        "allrounder",
        "bowler",
    }
)


def _parse_slot_types(slot_types_param: str | None, n: int) -> list[str]:
    if not slot_types_param or not str(slot_types_param).strip():
        return [
            _DEFAULT_SLOT_SEQUENCE[i] if i < len(_DEFAULT_SLOT_SEQUENCE) else "bowler"
            for i in range(n)
        ]
    parts = [p.strip().lower() for p in str(slot_types_param).split(",") if p.strip()]
    out = [p if p in _VALID_SLOT_TYPES else "bowler" for p in parts]
    while len(out) < n:
        i = len(out)
        out.append(
            _DEFAULT_SLOT_SEQUENCE[i] if i < len(_DEFAULT_SLOT_SEQUENCE) else "bowler"
        )
    return out[:n]


def _parse_bowling_phases(param: str | None, n: int) -> list[str | None]:
    if not param or not str(param).strip():
        return [None] * n
    out: list[str | None] = []
    for p in str(param).split(","):
        t = p.strip().lower()
        if t in ("pp", "powerplay", "pp_heavy"):
            out.append("pp_heavy")
        elif t in ("middle", "mid", "middle_heavy"):
            out.append("middle_heavy")
        elif t in ("death", "death_heavy"):
            out.append("death_heavy")
        elif t in ("", "-", "none", "na"):
            out.append(None)
        else:
            out.append(None)
    while len(out) < n:
        out.append(None)
    return out[:n]


def _allrounder_classify(
    bat_row: dict | None,
    bowl_row: dict | None,
    is_genuine_bat: bool,
    is_genuine_bowl: bool,
) -> str | None:
    if not (bat_row and bowl_row and is_genuine_bat and is_genuine_bowl):
        return None
    bat_arch = _safe_str(bat_row.get("archetype"), "")
    bowl_arch = _safe_str(bowl_row.get("archetype"), "")
    if bat_arch == "All-Round Elite" and (
        bowl_arch == "All-Round Threat" or bowl_arch in _BOWLING_ARCHETYPES
    ):
        return "genuine"
    try:
        wb = float(
            bat_row.get("war_batting")
            or bat_row.get("composite_batting")
            or bat_row.get("overall_score")
            or 0
        )
        wl = float(
            bowl_row.get("war_bowling")
            or bowl_row.get("composite_bowling")
            or bowl_row.get("overall_score")
            or 0
        )
    except (TypeError, ValueError):
        wb, wl = 0.0, 0.0
    if bowl_arch in _BOWLING_ARCHETYPES and wl >= wb * 0.9:
        return "bowling"
    if bat_arch in _BATTING_ARCHETYPES and wb >= wl * 0.9:
        return "batting"
    return "genuine"


def _is_bowling_role_slot(slot: str) -> bool:
    return slot in ("bowler", "allrounder")


def _bowl_matches(row: dict) -> int:
    return _safe_int(row.get("matches")) or 0


def _include_in_bowling_aggregate(
    slot_type: str,
    bowl_row: dict,
    bat_row: dict | None,
    is_genuine_bat: bool,
    is_genuine_bowl: bool,
) -> bool:
    if not bowl_row or not is_genuine_bowl:
        return False
    bowl_arch = _safe_str(bowl_row.get("archetype"), "")
    matches = _bowl_matches(bowl_row)
    if bowl_arch in _BOWLING_ARCHETYPES:
        return True
    if bat_row and is_genuine_bat:
        if _safe_str(bat_row.get("archetype"), "") == "All-Round Elite" and (
            bowl_arch == "All-Round Threat" or bowl_arch in _BOWLING_ARCHETYPES
        ):
            return True
    if _is_bowling_role_slot(slot_type) and matches >= 10:
        return True
    return False


def _effective_phase_group(bowl_row: dict, user_phase: str | None) -> str | None:
    if user_phase:
        return user_phase
    return _normalise_phase_group(bowl_row.get("phase_group"))


def _bowler_covers_death(bowl_row: dict, user_phase: str | None) -> bool:
    arch = _safe_str(bowl_row.get("archetype"), "")
    if "Death" in arch:
        return True
    return _effective_phase_group(bowl_row, user_phase) == "death_heavy"


def _bowler_covers_pp(bowl_row: dict, user_phase: str | None) -> bool:
    arch = _safe_str(bowl_row.get("archetype"), "")
    if "Powerplay" in arch or arch == "Powerplay Enforcer":
        return True
    return _effective_phase_group(bowl_row, user_phase) == "pp_heavy"


def _is_spin_bowler_row(bowl_row: dict) -> bool:
    arch = _safe_str(bowl_row.get("archetype"), "").lower()
    if "spin" in arch or "spinner" in arch:
        return True
    style = _safe_str(bowl_row.get("bowling_style"), "").lower()
    return any(
        k in style for k in ("spin", "orthodox", "wrist", "leg break", "off break")
    )


def _death_entry_finisher_ok(store: Any, batter_id: str, bat_row: dict | None) -> bool:
    if not bat_row:
        return False
    cdf = getattr(store, "bat_careers_ctx_entry_death", None)
    if cdf is None or cdf.empty or "batter_id" not in cdf.columns:
        return False
    mask = cdf["batter_id"] == batter_id
    sub = cdf.loc[mask]
    if sub.empty:
        return False
    row = sub.iloc[0]
    spow = _safe_float(row.get("score_power"))
    if spow is not None and spow >= 58.0:
        return True
    sr = _safe_float(row.get("career_sr"))
    return sr is not None and sr >= 135.0


def _role_fit_warnings_for_slot(
    slot_type: str,
    bat_row: dict | None,
    is_genuine_bat: bool,
    name: str,
) -> list[str]:
    out: list[str] = []
    if not bat_row or not is_genuine_bat:
        return out
    mp = _safe_int(bat_row.get("modal_position"))
    if mp is None or not (1 <= mp <= 11):
        return out
    arch = _safe_str(bat_row.get("archetype"), "")
    if slot_type == "opener" and mp not in (1, 2) and "Opener" not in arch:
        out.append(
            f"{name}: usually bats ~#{mp}; opener slot is atypical (role fit)."
        )
    elif slot_type == "finisher_wk" and mp <= 3:
        out.append(
            f"{name}: often top-order (~#{mp}); finisher/WK slot may be a role mismatch."
        )
    elif slot_type == "middle_order" and mp in (1, 2) and "Opener" not in arch:
        out.append(
            f"{name}: modal top-order (~#{mp}); middle-order slot is atypical."
        )
    return out


def _evaluate_composition(
    entries: list[dict], store: Any
) -> tuple[list[str], list[str], dict[str, bool | str]]:
    critical: list[str] = []
    advisory: list[str] = []
    summary: dict[str, bool | str] = {}

    bowling_pool: list[dict] = []
    for e in entries:
        br = e["bowl_row"]
        if not br:
            continue
        if e["is_genuine_bowl"] or (
            _is_bowling_role_slot(e["slot_type"]) and _bowl_matches(br) >= 5
        ):
            bowling_pool.append(e)

    n_pool = len(bowling_pool)
    summary["bowling_options_count"] = str(n_pool)
    if n_pool < 6:
        critical.append(
            f"Fewer than six realistic bowling options (have {n_pool})."
        )
    summary["sixth_bowler_ok"] = n_pool >= 6

    has_death = any(
        _bowler_covers_death(b["bowl_row"], b.get("user_bowl_phase"))
        for b in bowling_pool
    )
    if not has_death and n_pool >= 3:
        critical.append("No clear death-phase bowling profile in the attack.")
    summary["death_covered"] = has_death

    has_pp_bowl = any(
        _bowler_covers_pp(b["bowl_row"], b.get("user_bowl_phase"))
        for b in bowling_pool
    )
    if not has_pp_bowl and n_pool >= 3:
        critical.append("No clear powerplay bowling profile in the attack.")
    summary["pp_bowling_covered"] = has_pp_bowl

    has_pp_bat = False
    for e in entries:
        if not e["is_genuine_bat"] or not e["bat_row"]:
            continue
        br = e["bat_row"]
        arch = _safe_str(br.get("archetype"), "")
        if e["slot_type"] == "opener" or "Opener" in arch:
            has_pp_bat = True
            break
        acc = _safe_float(br.get("score_acceleration"))
        if acc is not None and acc >= 55:
            has_pp_bat = True
            break
    if not has_pp_bat and len(entries) >= 5:
        critical.append("Limited powerplay batting intent in the top order.")
    summary["pp_batting_covered"] = has_pp_bat

    fin_ok = False
    for e in entries:
        if not e["is_genuine_bat"] or not e["bat_row"]:
            continue
        br = e["bat_row"]
        arch = _safe_str(br.get("archetype"), "")
        if "Finish" in arch and e["slot_type"] in (
            "finisher_wk",
            "middle_order",
            "allrounder",
        ):
            fin_ok = True
            break
        if _death_entry_finisher_ok(store, e["pid"], br):
            fin_ok = True
            break
    if not fin_ok and len(entries) >= 6:
        critical.append("Finisher / late-entry batting strength is unclear.")
    summary["finisher_depth_ok"] = fin_ok

    strong_spinners = [
        b
        for b in bowling_pool
        if _is_spin_bowler_row(b["bowl_row"]) and _bowl_matches(b["bowl_row"]) >= 10
    ]
    any_spin = any(
        _is_spin_bowler_row(b["bowl_row"]) for b in bowling_pool
    )
    if not any_spin:
        advisory.append(
            "No clear spin option in the attack (may matter on slower surfaces)."
        )
    elif not strong_spinners:
        advisory.append("Spin appears part-time or low-volume only.")

    return critical, advisory, summary


def _pick_balanced_bowler_ids(bowl_df: Any, exclude: set[str], k: int) -> list[str]:
    """Prefer at least one death- and one powerplay-profile bowler when available."""
    if bowl_df is None or getattr(bowl_df, "empty", True) or k <= 0:
        return []
    taken: list[str] = []
    bid_col = "bowler_id"

    def walk(pred) -> None:
        nonlocal taken
        if len(taken) >= k:
            return
        for _, row in bowl_df.iterrows():
            if len(taken) >= k:
                return
            bid = str(row.get(bid_col, "") or "")
            if not bid or bid in exclude or bid in taken:
                continue
            if pred(row):
                taken.append(bid)

    walk(lambda row: _bowler_covers_death(row.to_dict(), None))
    walk(lambda row: _bowler_covers_pp(row.to_dict(), None))

    for _, row in bowl_df.iterrows():
        if len(taken) >= k:
            break
        bid = str(row.get(bid_col, "") or "")
        if bid and bid not in exclude and bid not in taken:
            taken.append(bid)
    return taken


def _handedness_advisory(entries: list[dict]) -> str | None:
    hands: list[str] = []
    for e in entries:
        br = e.get("bat_row")
        if not br:
            continue
        h = _safe_str(br.get("batting_hand"), "").strip().upper()[:1]
        if h in ("L", "R"):
            hands.append(h)
    if len(hands) < 6:
        return None
    if len(set(hands)) == 1:
        return "Batting lineup is single-handed; variety can help matchups."
    return None


def _avg_col(rows: list, col: str) -> float | None:
    """Compute the average of a column across a list of row dicts, ignoring NaN."""
    values = []
    for r in rows:
        v = r.get(col)
        if v is not None:
            try:
                f = float(v)
                if not math.isnan(f) and not math.isinf(f):
                    values.append(f)
            except (TypeError, ValueError):
                pass
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _sum_col(rows: list, col: str) -> float | None:
    """Sum a column across a list of row dicts, ignoring NaN."""
    values = []
    for r in rows:
        v = r.get(col)
        if v is not None:
            try:
                f = float(v)
                if not math.isnan(f) and not math.isinf(f):
                    values.append(f)
            except (TypeError, ValueError):
                pass
    if not values:
        return None
    return round(sum(values), 2)


def _detect_weaknesses(
    bat_rows: list,
    bowl_rows: list,
    store: Any,
) -> list[str]:
    """Detect team weaknesses (dimensions below 50th percentile).

    Compares the team's average scores against the 50th percentile of
    *genuine* batters / bowlers only (excluding tail-enders and part-timers).
    """
    import pandas as pd

    weaknesses: list[str] = []

    # ── Batting dimension checks (against genuine batters only) ───
    genuine_batters = _get_genuine_batters_df(store)

    bat_dimensions = [
        ("score_acceleration", "Batting acceleration"),
        ("score_power", "Batting power"),
        ("score_control", "Batting control"),
    ]

    for col, label in bat_dimensions:
        team_avg = _avg_col(bat_rows, col)
        if team_avg is None:
            continue

        if not genuine_batters.empty and col in genuine_batters.columns:
            valid = pd.to_numeric(genuine_batters[col], errors="coerce").dropna()
            if len(valid) > 0:
                p50 = float(valid.quantile(0.5))
                if team_avg < p50:
                    weaknesses.append(
                        f"{label} below average (team avg {team_avg:.1f} vs median {p50:.1f})"
                    )

    # ── Bowling dimension checks (against genuine bowlers only) ───
    genuine_bowlers = _get_genuine_bowlers_df(store)

    bowl_dimensions = [
        ("score_accuracy", "Bowling accuracy"),
        ("score_control", "Bowling control"),
        ("score_threat", "Bowling threat"),
    ]

    for col, label in bowl_dimensions:
        team_avg = _avg_col(bowl_rows, col)
        if team_avg is None:
            continue

        if not genuine_bowlers.empty and col in genuine_bowlers.columns:
            valid = pd.to_numeric(genuine_bowlers[col], errors="coerce").dropna()
            if len(valid) > 0:
                p50 = float(valid.quantile(0.5))
                if team_avg < p50:
                    weaknesses.append(
                        f"{label} below average (team avg {team_avg:.1f} vs median {p50:.1f})"
                    )

    # ── Structural checks ─────────────────────────────────────────
    if len(bat_rows) == 0:
        weaknesses.append("No batters selected")
    if len(bowl_rows) == 0:
        weaknesses.append("No bowlers selected")
    if len(bat_rows) > 7:
        weaknesses.append("Too many batters (max recommended: 7)")
    if len(bowl_rows) < 4 and len(bowl_rows) > 0:
        weaknesses.append(f"Fewer than 4 specialist bowlers (have {len(bowl_rows)})")

    return weaknesses


# ── Endpoints ─────────────────────────────────────────────────────


@router.get(
    "/team/analyse",
    response_model=TeamAnalysis,
    summary="Analyse a team selection",
)
async def analyse_team(
    ids: str = Query(
        ...,
        description="Comma-separated player IDs (up to 11)",
        examples=["id1,id2,id3"],
    ),
    slot_types: str | None = Query(
        None,
        description=(
            "Comma-separated slot types aligned with ids: "
            "opener, top_order, middle_order, finisher_wk, allrounder, bowler. "
            "Drives role fit and which part-timers count in bowling averages."
        ),
    ),
    bowling_phases: str | None = Query(
        None,
        description=(
            "Optional comma-aligned phase tags: pp, middle, death, or empty. "
            "Overrides phase for composition checks."
        ),
    ),
    store=Depends(_get_store),
):
    """Analyse a team selection and return aggregate metrics.

    Accepts a comma-separated list of player IDs (mix of batters and bowlers,
    up to 11).  An optional ``slot_types`` parameter is accepted for URL
    backward-compatibility but is **ignored** for role classification.

    Role classification is determined entirely from the player's actual
    data using the ``_is_genuine_batter`` and ``_is_genuine_bowler``
    heuristics:

    - If a player exists in ``bat_careers`` and passes the genuine-batter
      check → included in batting aggregates.
    - If a player exists in ``bowl_careers`` and passes the genuine-bowler
      check → included in bowling aggregates.
    - Players who pass both checks are included in both (all-rounders).
    - If a player exists in a dataset but does *not* pass the genuine
      check for that role, they are still included if they have **no**
      record in the other dataset (so every player appears in at least
      one role).

    Returns:

    - Individual player summaries (split by role)
    - Average batting scores (acceleration, power, control)
    - Average bowling scores (accuracy, control, threat)
    - Total WAR (batting + bowling)
    - Average clutch index
    - Detected weaknesses (dimensions below 50th percentile)
    """
    player_ids = [pid.strip() for pid in ids.split(",") if pid.strip()]

    if len(player_ids) == 0:
        raise HTTPException(status_code=400, detail="No player IDs provided")
    if len(player_ids) > 15:
        raise HTTPException(
            status_code=400,
            detail="Maximum 15 player IDs allowed (11 players + subs)",
        )

    n = len(player_ids)
    slots = _parse_slot_types(slot_types, n)
    user_phases = _parse_bowling_phases(bowling_phases, n)

    batter_summaries: list[PlayerSummary] = []
    bowler_summaries: list[PlayerSummary] = []
    bat_rows: list[dict] = []
    bowl_rows_agg: list[dict] = []
    entries: list[dict] = []

    for idx, pid in enumerate(player_ids):
        slot_type = slots[idx] if idx < len(slots) else "bowler"
        user_phase = user_phases[idx] if idx < len(user_phases) else None

        bat_row_dict: dict | None = None
        bowl_row_dict: dict | None = None

        if not store.bat_careers.empty and "batter_id" in store.bat_careers.columns:
            mask = store.bat_careers["batter_id"] == pid
            matches = store.bat_careers.loc[mask]
            if not matches.empty:
                bat_row_dict = matches.iloc[0].to_dict()

        if not store.bowl_careers.empty and "bowler_id" in store.bowl_careers.columns:
            mask = store.bowl_careers["bowler_id"] == pid
            matches = store.bowl_careers.loc[mask]
            if not matches.empty:
                bowl_row_dict = matches.iloc[0].to_dict()

        if bat_row_dict is None and bowl_row_dict is None:
            continue

        is_genuine_bat = (
            _is_genuine_batter(bat_row_dict, store) if bat_row_dict else False
        )
        is_genuine_bowl = (
            _is_genuine_bowler(bowl_row_dict, store) if bowl_row_dict else False
        )

        if not is_genuine_bat and not is_genuine_bowl:
            if bat_row_dict and not bowl_row_dict:
                is_genuine_bat = True
            elif bowl_row_dict and not bat_row_dict:
                is_genuine_bowl = True
            elif bat_row_dict and bowl_row_dict:
                bat_score = bat_row_dict.get("overall_score") or bat_row_dict.get(
                    "composite_batting", 0
                )
                bowl_score = bowl_row_dict.get("overall_score") or bowl_row_dict.get(
                    "composite_bowling", 0
                )
                try:
                    if float(bat_score or 0) >= float(bowl_score or 0):
                        is_genuine_bat = True
                    else:
                        is_genuine_bowl = True
                except (TypeError, ValueError):
                    is_genuine_bat = True

        display_name = _safe_str(
            (bat_row_dict or {}).get("batter")
            or (bowl_row_dict or {}).get("bowler")
            or "Unknown",
            "Unknown",
        )
        ar_class = _allrounder_classify(
            bat_row_dict, bowl_row_dict, is_genuine_bat, is_genuine_bowl
        )

        if is_genuine_bat and bat_row_dict:
            batter_summaries.append(
                _row_to_player_summary(bat_row_dict, "bat", allrounder_class=ar_class)
            )
            bat_rows.append(bat_row_dict)

        show_bowl = bool(
            bowl_row_dict
            and (
                is_genuine_bowl
                or (
                    _is_bowling_role_slot(slot_type)
                    and _bowl_matches(bowl_row_dict) >= 5
                )
            )
        )
        if show_bowl and bowl_row_dict:
            bowler_summaries.append(
                _row_to_player_summary(
                    bowl_row_dict,
                    "bowl",
                    phase_group=user_phase,
                    allrounder_class=ar_class,
                )
            )

        if bowl_row_dict and _include_in_bowling_aggregate(
            slot_type,
            bowl_row_dict,
            bat_row_dict,
            is_genuine_bat,
            is_genuine_bowl,
        ):
            bowl_rows_agg.append(bowl_row_dict)

        entries.append(
            {
                "pid": pid,
                "name": display_name,
                "slot_type": slot_type,
                "bat_row": bat_row_dict,
                "bowl_row": bowl_row_dict,
                "is_genuine_bat": is_genuine_bat,
                "is_genuine_bowl": is_genuine_bowl,
                "user_bowl_phase": user_phase,
            }
        )

    avg_acceleration = _avg_col(bat_rows, "score_acceleration")
    avg_bat_power = _avg_col(bat_rows, "score_power")
    avg_bat_control = _avg_col(bat_rows, "score_control")

    avg_accuracy = _avg_col(bowl_rows_agg, "score_accuracy")
    avg_bowl_control = _avg_col(bowl_rows_agg, "score_control")
    avg_threat = _avg_col(bowl_rows_agg, "score_threat")

    total_war_batting = _sum_col(bat_rows, "war_batting")
    total_war_bowling = _sum_col(bowl_rows_agg, "war_bowling")

    all_clutch_vals: list[dict] = []
    for r in bat_rows:
        ci = r.get("clutch_index") or r.get("clutch_index_bat")
        if ci is not None:
            all_clutch_vals.append({"clutch": ci})
    for r in bowl_rows_agg:
        ci = r.get("clutch_index_bowl")
        if ci is not None:
            all_clutch_vals.append({"clutch": ci})
    avg_clutch = _avg_col(all_clutch_vals, "clutch")

    weaknesses = _detect_weaknesses(bat_rows, bowl_rows_agg, store)

    comp_crit, comp_adv, comp_summary = _evaluate_composition(entries, store)
    hnote = _handedness_advisory(entries)
    if hnote:
        comp_adv = [*comp_adv, hnote]

    role_fit_warnings: list[str] = []
    for e in entries:
        role_fit_warnings.extend(
            _role_fit_warnings_for_slot(
                e["slot_type"],
                e["bat_row"],
                e["is_genuine_bat"],
                e["name"],
            )
        )

    seen_bat_ids: set[str] = set()
    unique_batters: list[PlayerSummary] = []
    for ps in batter_summaries:
        if ps.id not in seen_bat_ids:
            seen_bat_ids.add(ps.id)
            unique_batters.append(ps)

    seen_bowl_ids: set[str] = set()
    unique_bowlers: list[PlayerSummary] = []
    for ps in bowler_summaries:
        if ps.id not in seen_bowl_ids:
            seen_bowl_ids.add(ps.id)
            unique_bowlers.append(ps)

    return TeamAnalysis(
        player_count=len(set(player_ids)),
        batters=unique_batters,
        bowlers=unique_bowlers,
        avg_acceleration=_safe_float(avg_acceleration),
        avg_bat_power=_safe_float(avg_bat_power),
        avg_bat_control=_safe_float(avg_bat_control),
        avg_accuracy=_safe_float(avg_accuracy),
        avg_bowl_control=_safe_float(avg_bowl_control),
        avg_threat=_safe_float(avg_threat),
        total_war_batting=_safe_float(total_war_batting),
        total_war_bowling=_safe_float(total_war_bowling),
        avg_clutch=_safe_float(avg_clutch),
        weaknesses=weaknesses,
        composition_critical=comp_crit,
        composition_advisory=comp_adv,
        role_fit_warnings=role_fit_warnings,
        composition_summary=comp_summary,
        genuine_batter_count=len(bat_rows),
        genuine_bowler_count=len(bowler_summaries),
        bowling_aggregate_count=len(bowl_rows_agg),
        player_ids_ordered=[e["pid"] for e in entries],
    )


@router.get(
    "/team/auto-fill",
    response_model=TeamAnalysis,
    summary="Auto-fill a team XI",
)
async def auto_fill_team(
    strategy: str = Query(
        "balanced",
        description=(
            "Auto-fill: balanced, bat_heavy, bowl_heavy, war, power, control, country"
        ),
    ),
    country: str | None = Query(
        None,
        description="Country filter (required for strategy='country')",
    ),
    exclude: str | None = Query(
        None,
        description="Comma-separated player IDs to exclude from auto-fill",
    ),
    store=Depends(_get_store),
):
    """Auto-fill a T20I XI based on a strategy.

    Strategies:
    - **war**: Pick the highest-WAR players (greedy, respecting positional constraints)
    - **power**: Maximise batting power + bowling threat
    - **control**: Maximise batting control + bowling control
    - **country**: Best XI from a single country (requires `country` param)

    Returns a TeamAnalysis with up to 11 players selected, including
    aggregate metrics and weakness detection.

    Positional constraints:
    - At least 5 bowlers (from bowling careers)
    - At most 7 batters
    - Greedy selection: pick best available for each slot
    """
    import pandas as pd

    if store.bat_careers.empty and store.bowl_careers.empty:
        raise HTTPException(
            status_code=404,
            detail="No player data available for auto-fill",
        )

    exclude_ids: set[str] = set()
    if exclude:
        exclude_ids = {pid.strip() for pid in exclude.split(",") if pid.strip()}

    # Determine sort column based on strategy
    bat_sort_col = "war_batting"
    bowl_sort_col = "war_bowling"

    if strategy == "power":
        bat_sort_col = "score_power"
        bowl_sort_col = "score_threat"
    elif strategy == "control":
        bat_sort_col = "score_control"
        bowl_sort_col = "score_control"
    elif strategy == "country":
        if not country:
            raise HTTPException(
                status_code=400,
                detail="Country parameter is required for strategy='country'",
            )
        bat_sort_col = "war_batting"
        bowl_sort_col = "war_bowling"
    elif strategy == "bat_heavy":
        bat_sort_col = "war_batting"
        bowl_sort_col = "war_bowling"
    elif strategy in ("balanced", "bowl_heavy"):
        bat_sort_col = "war_batting"
        bowl_sort_col = "war_bowling"

    # ── Filter and sort batters ───────────────────────────────
    bat_df = store.bat_careers.copy() if not store.bat_careers.empty else pd.DataFrame()
    if not bat_df.empty:
        # Remove provisionals for auto-fill
        if "is_provisional_bat" in bat_df.columns:
            bat_df = bat_df[bat_df["is_provisional_bat"] != True]  # noqa: E712

        # Country filter
        if strategy == "country" and country:
            if "country" in bat_df.columns:
                bat_df = bat_df[bat_df["country"].str.lower() == country.lower()]

        # Exclude specified IDs
        if exclude_ids and "batter_id" in bat_df.columns:
            bat_df = bat_df[~bat_df["batter_id"].isin(exclude_ids)]

        # Sort by the chosen metric (descending)
        if bat_sort_col in bat_df.columns:
            bat_df[bat_sort_col] = pd.to_numeric(bat_df[bat_sort_col], errors="coerce")
            bat_df = bat_df.sort_values(
                bat_sort_col, ascending=False, na_position="last"
            )

    # ── Filter and sort bowlers ───────────────────────────────
    bowl_df = (
        store.bowl_careers.copy() if not store.bowl_careers.empty else pd.DataFrame()
    )
    if not bowl_df.empty:
        if "is_provisional_bowl" in bowl_df.columns:
            bowl_df = bowl_df[bowl_df["is_provisional_bowl"] != True]  # noqa: E712

        if strategy == "country" and country:
            if "country" in bowl_df.columns:
                bowl_df = bowl_df[bowl_df["country"].str.lower() == country.lower()]

        if exclude_ids and "bowler_id" in bowl_df.columns:
            bowl_df = bowl_df[~bowl_df["bowler_id"].isin(exclude_ids)]

        if bowl_sort_col in bowl_df.columns:
            bowl_df[bowl_sort_col] = pd.to_numeric(
                bowl_df[bowl_sort_col], errors="coerce"
            )
            bowl_df = bowl_df.sort_values(
                bowl_sort_col, ascending=False, na_position="last"
            )

    # ── Greedy selection (batters listed before bowlers in XI order) ──
    if strategy == "bowl_heavy":
        max_bowlers, max_batters = 6, 5
    else:
        max_bowlers, max_batters = 5, 6

    selected_ids: set[str] = set()
    bowl_ids_ordered: list[str] = []

    if strategy == "balanced":
        bowl_ids_ordered = _pick_balanced_bowler_ids(
            bowl_df, exclude_ids, max_bowlers
        )
        selected_ids.update(bowl_ids_ordered)
    elif not bowl_df.empty:
        for _, row in bowl_df.iterrows():
            if len(bowl_ids_ordered) >= max_bowlers:
                break
            bid = str(row.get("bowler_id", "") or "")
            if bid and bid not in selected_ids:
                selected_ids.add(bid)
                bowl_ids_ordered.append(bid)

    bat_ids_ordered: list[str] = []
    if not bat_df.empty:
        for _, row in bat_df.iterrows():
            if len(bat_ids_ordered) >= max_batters:
                break
            bid = str(row.get("batter_id", "") or "")
            if bid and bid not in selected_ids:
                selected_ids.add(bid)
                bat_ids_ordered.append(bid)

    if len(selected_ids) < 11 and not bowl_df.empty:
        for _, row in bowl_df.iterrows():
            if len(selected_ids) >= 11:
                break
            bid = str(row.get("bowler_id", "") or "")
            if bid and bid not in selected_ids:
                selected_ids.add(bid)
                bowl_ids_ordered.append(bid)

    if strategy == "bat_heavy" and len(bat_ids_ordered) < max_batters and not bat_df.empty:
        for _, row in bat_df.iterrows():
            if len(bat_ids_ordered) >= max_batters:
                break
            bid = str(row.get("batter_id", "") or "")
            if bid and bid not in selected_ids:
                selected_ids.add(bid)
                bat_ids_ordered.append(bid)

    xi_ids = bat_ids_ordered + bowl_ids_ordered
    xi_ids = xi_ids[:11]
    slot_str = ",".join(
        _DEFAULT_SLOT_SEQUENCE[i] if i < len(_DEFAULT_SLOT_SEQUENCE) else "bowler"
        for i in range(len(xi_ids))
    )
    return await analyse_team(
        ids=",".join(xi_ids),
        slot_types=slot_str,
        bowling_phases=None,
        store=store,
    )


# ── Team vs Team Comparison ───────────────────────────────────────


@router.get(
    "/team/compare",
    summary="Compare two teams side-by-side",
)
async def compare_teams(
    team_a: str = Query(
        ...,
        description="Comma-separated player IDs for Team A (up to 11)",
        examples=["id1,id2,id3"],
    ),
    team_b: str = Query(
        ...,
        description="Comma-separated player IDs for Team B (up to 11)",
        examples=["id4,id5,id6"],
    ),
    store=Depends(_get_store),
):
    """Compare two team selections side-by-side.

    Reuses the ``analyse_team`` logic for each team and returns both
    analyses plus a high-level comparison summary indicating which
    team has the edge in batting, bowling, and overall WAR.
    """
    analysis_a = await analyse_team(ids=team_a, store=store)
    analysis_b = await analyse_team(ids=team_b, store=store)

    # ── Compute edge indicators ───────────────────────────────
    def _edge(val_a: float | None, val_b: float | None) -> str:
        a = val_a or 0.0
        b = val_b or 0.0
        if abs(a - b) < 0.5:
            return "even"
        return "A" if a > b else "B"

    bat_sum_a = (
        (analysis_a.avg_acceleration or 0)
        + (analysis_a.avg_bat_power or 0)
        + (analysis_a.avg_bat_control or 0)
    )
    bat_sum_b = (
        (analysis_b.avg_acceleration or 0)
        + (analysis_b.avg_bat_power or 0)
        + (analysis_b.avg_bat_control or 0)
    )

    bowl_sum_a = (
        (analysis_a.avg_accuracy or 0)
        + (analysis_a.avg_bowl_control or 0)
        + (analysis_a.avg_threat or 0)
    )
    bowl_sum_b = (
        (analysis_b.avg_accuracy or 0)
        + (analysis_b.avg_bowl_control or 0)
        + (analysis_b.avg_threat or 0)
    )

    war_a = (analysis_a.total_war_batting or 0) + (analysis_a.total_war_bowling or 0)
    war_b = (analysis_b.total_war_batting or 0) + (analysis_b.total_war_bowling or 0)

    return {
        "team_a": analysis_a,
        "team_b": analysis_b,
        "comparison": {
            "batting_edge": _edge(bat_sum_a, bat_sum_b),
            "batting_diff": round(bat_sum_a - bat_sum_b, 2),
            "bowling_edge": _edge(bowl_sum_a, bowl_sum_b),
            "bowling_diff": round(bowl_sum_a - bowl_sum_b, 2),
            "war_edge": _edge(war_a, war_b),
            "war_diff": round(war_a - war_b, 2),
            "clutch_edge": _edge(analysis_a.avg_clutch, analysis_b.avg_clutch),
        },
    }
