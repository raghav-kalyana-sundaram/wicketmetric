"""
Team Builder router — /api/team endpoints.

Provides:
- GET /api/team/analyse   → Aggregate team analysis for a set of player IDs
- GET /api/team/auto-fill → Suggested XI based on a strategy (war, power, control, country)
- GET /api/team/compare   → Compare two teams side-by-side

These endpoints support the Team Builder page (gui.md § 6.8), which lets
users assemble hypothetical T20I XIs and see aggregate team metrics,
a team radar chart, and weakness detection.
"""

from __future__ import annotations

import math
from typing import Any

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query
from db import safe_float, safe_int, safe_str, safe_fmt, query_one, query_all
from rating_display import batting_display_ratings, bowling_display_ratings
from schemas import PlayerSummary, TeamAnalysis

router = APIRouter(prefix="/api", tags=["team"])


# ── Dependency placeholder (overridden in app.py) ─────────────────


def _get_store():
    raise HTTPException(
        status_code=503,
        detail="Data store not initialised (dependency override missing).",
    )


# ── Helpers ───────────────────────────────────────────────────────


def _normalise_phase_group(raw: Any) -> str | None:
    s = safe_str(raw, "").strip().lower()
    if not s or s in ("unknown", "nan", "none"):
        return None
    return s


def _row_to_player_summary(
    row: dict,
    role: str,
    *,
    phase_group: str | None = None,
    allrounder_class: str | None = None,
) -> PlayerSummary:
    """Convert a dict career row to a PlayerSummary."""
    if role == "bat":
        rating_overall, rating_current = batting_display_ratings(row)
        mp = safe_int(row.get("modal_position"))
        modal_position = mp if mp is not None and 1 <= mp <= 11 else None
        return PlayerSummary(
            id=safe_str(row.get("batter_id"), ""),
            name=safe_str(row.get("batter"), "Unknown"),
            country=safe_str(row.get("country"), ""),
            role="bat",
            archetype=safe_str(row.get("archetype"), ""),
            grade_overall=safe_str(row.get("overall_grade"), "D"),
            innings_count=safe_int(row.get("innings_count")),
            total_runs=safe_int(row.get("total_runs")),
            career_sr=safe_float(row.get("career_sr")),
            career_avg=safe_float(row.get("career_avg")),
            score_1=safe_float(row.get("score_acceleration")),
            score_2=safe_float(row.get("score_power")),
            score_3=safe_float(row.get("score_control")),
            score_1_label="acceleration",
            score_2_label="power",
            score_3_label="control",
            is_provisional=bool(row.get("is_provisional_bat", True)),
            overall_score=safe_float(row.get("overall_score"))
            or safe_float(row.get("composite_batting")),
            rating_current=rating_current,
            rating_overall=rating_overall,
            modal_position=modal_position,
            recent_team=safe_str(row.get("recent_team"), "").strip() or None,
            phase_group=None,
            allrounder_class=allrounder_class,
        )
    else:
        rating_overall, rating_current = bowling_display_ratings(row)
        pg = phase_group if phase_group is not None else _normalise_phase_group(
            row.get("phase_group")
        )
        return PlayerSummary(
            id=safe_str(row.get("bowler_id"), ""),
            name=safe_str(row.get("bowler"), "Unknown"),
            country=safe_str(row.get("country"), ""),
            role="bowl",
            archetype=safe_str(row.get("archetype"), ""),
            grade_overall=safe_str(row.get("overall_grade"), "D"),
            innings_count=safe_int(row.get("matches")),
            total_runs=safe_int(row.get("total_wickets")),
            career_sr=safe_float(row.get("career_economy")),
            career_avg=None,
            score_1=safe_float(row.get("score_accuracy")),
            score_2=safe_float(row.get("score_control")),
            score_3=safe_float(row.get("score_threat")),
            score_1_label="accuracy",
            score_2_label="control",
            score_3_label="threat",
            is_provisional=bool(row.get("is_provisional_bowl", True)),
            overall_score=safe_float(row.get("overall_score"))
            or safe_float(row.get("composite_bowling")),
            rating_current=rating_current,
            rating_overall=rating_overall,
            modal_position=None,
            recent_team=safe_str(row.get("recent_team"), "").strip() or None,
            phase_group=pg,
            allrounder_class=allrounder_class,
        )


# ── Archetype-based role classification ───────────────────────────

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


def _is_genuine_bowler(bowl_row: dict, conn: duckdb.DuckDBPyConnection, fmt: str) -> bool:
    """Determine if a player is a genuine bowler.

    Classification priority:
    1. Archetype label — known bowling archetype → genuine bowler.
    2. Fallback heuristic — ≥10 matches AND bowl/bat ratio ≥ 0.40.
    """
    archetype = str(bowl_row.get("archetype", "") or "").strip()
    if archetype in _BOWLING_ARCHETYPES:
        return True
    if archetype in _BATTING_ARCHETYPES:
        return False

    bowl_matches = float(bowl_row.get("matches", 0) or 0)
    if bowl_matches < 10:
        return False

    bowler_id = str(bowl_row.get("bowler_id", ""))
    if not bowler_id:
        return True

    bat_row = query_one(
        conn,
        f"SELECT innings_count FROM {fmt}.bat_careers WHERE batter_id = ?",
        [bowler_id],
    )
    if bat_row is None:
        return True

    bat_innings = float(bat_row.get("innings_count", 0) or 0)
    if bat_innings <= 0:
        return True

    ratio = bowl_matches / bat_innings
    return ratio >= 0.40


def _is_genuine_batter(bat_row: dict) -> bool:
    """Determine if a player contributes meaningfully with the bat.

    Classification priority:
    1. Archetype label — known batting archetype → genuine batter.
    2. Fallback heuristic — ≥10 innings AND composite ≥ 20.
    """
    archetype = str(bat_row.get("archetype", "") or "").strip()
    if archetype in _BATTING_ARCHETYPES:
        return True
    if archetype in _BOWLING_ARCHETYPES:
        return False

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


def _get_genuine_bowler_rows(conn: duckdb.DuckDBPyConnection, fmt: str) -> list[dict]:
    """Return bowl_careers rows for genuine bowlers only."""
    all_rows = query_all(conn, f"SELECT * FROM {fmt}.bowl_careers")
    return [r for r in all_rows if _is_genuine_bowler(r, conn, fmt)]


def _get_genuine_batter_rows(conn: duckdb.DuckDBPyConnection, fmt: str) -> list[dict]:
    """Return bat_careers rows for genuine batters only."""
    all_rows = query_all(conn, f"SELECT * FROM {fmt}.bat_careers")
    return [r for r in all_rows if _is_genuine_batter(r)]


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
    bat_arch = safe_str(bat_row.get("archetype"), "")
    bowl_arch = safe_str(bowl_row.get("archetype"), "")
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
    return safe_int(row.get("matches"))


def _include_in_bowling_aggregate(
    slot_type: str,
    bowl_row: dict,
    bat_row: dict | None,
    is_genuine_bat: bool,
    is_genuine_bowl: bool,
) -> bool:
    if not bowl_row or not is_genuine_bowl:
        return False
    bowl_arch = safe_str(bowl_row.get("archetype"), "")
    matches = _bowl_matches(bowl_row)
    if bowl_arch in _BOWLING_ARCHETYPES:
        return True
    if bat_row and is_genuine_bat:
        if safe_str(bat_row.get("archetype"), "") == "All-Round Elite" and (
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
    arch = safe_str(bowl_row.get("archetype"), "")
    if "Death" in arch:
        return True
    return _effective_phase_group(bowl_row, user_phase) == "death_heavy"


def _bowler_covers_pp(bowl_row: dict, user_phase: str | None) -> bool:
    arch = safe_str(bowl_row.get("archetype"), "")
    if "Powerplay" in arch or arch == "Powerplay Enforcer":
        return True
    return _effective_phase_group(bowl_row, user_phase) == "pp_heavy"


def _is_spin_bowler_row(bowl_row: dict) -> bool:
    kind = safe_str(bowl_row.get("bowling_kind"), "").lower()
    if kind == "spin":
        return True
    arch = safe_str(bowl_row.get("archetype"), "").lower()
    if "spin" in arch or "spinner" in arch:
        return True
    style = safe_str(bowl_row.get("bowling_style"), "").lower()
    return any(
        k in style for k in ("spin", "orthodox", "wrist", "leg break", "off break")
    )


def _death_entry_finisher_ok(
    conn: duckdb.DuckDBPyConnection, fmt: str, batter_id: str, bat_row: dict | None,
) -> bool:
    if not bat_row:
        return False
    try:
        ctx_row = query_one(
            conn,
            f"SELECT score_power, career_sr FROM {fmt}.bat_careers_ctx_entry_death WHERE batter_id = ?",
            [batter_id],
        )
    except duckdb.CatalogException:
        return False
    if ctx_row is None:
        return False
    spow = safe_float(ctx_row.get("score_power"))
    if spow is not None and spow >= 58.0:
        return True
    sr = safe_float(ctx_row.get("career_sr"))
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
    mp = safe_int(bat_row.get("modal_position"))
    if mp is None or not (1 <= mp <= 11):
        return out
    arch = safe_str(bat_row.get("archetype"), "")
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
    entries: list[dict], conn: duckdb.DuckDBPyConnection, fmt: str,
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
        arch = safe_str(br.get("archetype"), "")
        if e["slot_type"] == "opener" or "Opener" in arch:
            has_pp_bat = True
            break
        acc = safe_float(br.get("score_acceleration"))
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
        arch = safe_str(br.get("archetype"), "")
        if "Finish" in arch and e["slot_type"] in (
            "finisher_wk",
            "middle_order",
            "allrounder",
        ):
            fin_ok = True
            break
        if _death_entry_finisher_ok(conn, fmt, e["pid"], br):
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


def _pick_balanced_bowler_ids(
    bowl_rows: list[dict], exclude: set[str], k: int,
) -> list[str]:
    """Prefer at least one death- and one powerplay-profile bowler when available."""
    if not bowl_rows or k <= 0:
        return []
    taken: list[str] = []

    def walk(pred) -> None:
        nonlocal taken
        if len(taken) >= k:
            return
        for row in bowl_rows:
            if len(taken) >= k:
                return
            bid = str(row.get("bowler_id", "") or "")
            if not bid or bid in exclude or bid in taken:
                continue
            if pred(row):
                taken.append(bid)

    walk(lambda row: _bowler_covers_death(row, None))
    walk(lambda row: _bowler_covers_pp(row, None))

    for row in bowl_rows:
        if len(taken) >= k:
            break
        bid = str(row.get("bowler_id", "") or "")
        if bid and bid not in exclude and bid not in taken:
            taken.append(bid)
    return taken


def _handedness_advisory(entries: list[dict]) -> str | None:
    hands: list[str] = []
    for e in entries:
        br = e.get("bat_row")
        if not br:
            continue
        h = safe_str(br.get("batting_hand"), "").strip().upper()[:1]
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


def _percentile_50(values: list[float]) -> float:
    """Compute 50th percentile (median) from a list of floats."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2.0
    return s[mid]


def _detect_weaknesses(
    bat_rows: list[dict],
    bowl_rows: list[dict],
    conn: duckdb.DuckDBPyConnection,
    fmt: str,
) -> list[str]:
    """Detect team weaknesses (dimensions below 50th percentile).

    Compares the team's average scores against the 50th percentile of
    *genuine* batters / bowlers only (excluding tail-enders and part-timers).
    """
    weaknesses: list[str] = []

    genuine_batters = _get_genuine_batter_rows(conn, fmt)

    bat_dimensions = [
        ("score_acceleration", "Batting acceleration"),
        ("score_power", "Batting power"),
        ("score_control", "Batting control"),
    ]

    for col, label in bat_dimensions:
        team_avg = _avg_col(bat_rows, col)
        if team_avg is None:
            continue
        pop_vals = []
        for r in genuine_batters:
            v = r.get(col)
            if v is not None:
                try:
                    fv = float(v)
                    if not math.isnan(fv) and not math.isinf(fv):
                        pop_vals.append(fv)
                except (TypeError, ValueError):
                    pass
        if pop_vals:
            p50 = _percentile_50(pop_vals)
            if team_avg < p50:
                weaknesses.append(
                    f"{label} below average (team avg {team_avg:.1f} vs median {p50:.1f})"
                )

    genuine_bowlers = _get_genuine_bowler_rows(conn, fmt)

    bowl_dimensions = [
        ("score_accuracy", "Bowling accuracy"),
        ("score_control", "Bowling control"),
        ("score_threat", "Bowling threat"),
    ]

    for col, label in bowl_dimensions:
        team_avg = _avg_col(bowl_rows, col)
        if team_avg is None:
            continue
        pop_vals = []
        for r in genuine_bowlers:
            v = r.get(col)
            if v is not None:
                try:
                    fv = float(v)
                    if not math.isnan(fv) and not math.isinf(fv):
                        pop_vals.append(fv)
                except (TypeError, ValueError):
                    pass
        if pop_vals:
            p50 = _percentile_50(pop_vals)
            if team_avg < p50:
                weaknesses.append(
                    f"{label} below average (team avg {team_avg:.1f} vs median {p50:.1f})"
                )

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
    db=Depends(_get_store),
):
    conn, fmt = db
    f = safe_fmt(fmt)

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

    placeholders = ", ".join(["?"] * len(player_ids))
    bat_rows_all = query_all(
        conn,
        f"SELECT * FROM {f}.bat_careers WHERE batter_id IN ({placeholders})",
        player_ids,
    )
    bowl_rows_all = query_all(
        conn,
        f"SELECT * FROM {f}.bowl_careers WHERE bowler_id IN ({placeholders})",
        player_ids,
    )

    bat_lookup: dict[str, dict] = {r["batter_id"]: r for r in bat_rows_all}
    bowl_lookup: dict[str, dict] = {r["bowler_id"]: r for r in bowl_rows_all}

    batter_summaries: list[PlayerSummary] = []
    bowler_summaries: list[PlayerSummary] = []
    bat_rows: list[dict] = []
    bowl_rows_agg: list[dict] = []
    entries: list[dict] = []

    for idx, pid in enumerate(player_ids):
        slot_type = slots[idx] if idx < len(slots) else "bowler"
        user_phase = user_phases[idx] if idx < len(user_phases) else None

        bat_row_dict = bat_lookup.get(pid)
        bowl_row_dict = bowl_lookup.get(pid)

        if bat_row_dict is None and bowl_row_dict is None:
            continue

        is_genuine_bat = (
            _is_genuine_batter(bat_row_dict) if bat_row_dict else False
        )
        is_genuine_bowl = (
            _is_genuine_bowler(bowl_row_dict, conn, f) if bowl_row_dict else False
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

        display_name = safe_str(
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

    weaknesses = _detect_weaknesses(bat_rows, bowl_rows_agg, conn, f)

    comp_crit, comp_adv, comp_summary = _evaluate_composition(entries, conn, f)
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
        avg_acceleration=safe_float(avg_acceleration),
        avg_bat_power=safe_float(avg_bat_power),
        avg_bat_control=safe_float(avg_bat_control),
        avg_accuracy=safe_float(avg_accuracy),
        avg_bowl_control=safe_float(avg_bowl_control),
        avg_threat=safe_float(avg_threat),
        total_war_batting=safe_float(total_war_batting),
        total_war_bowling=safe_float(total_war_bowling),
        avg_clutch=safe_float(avg_clutch),
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
    db=Depends(_get_store),
):
    conn, fmt = db
    f = safe_fmt(fmt)

    bat_count_sql = f"SELECT COUNT(*) AS c FROM {f}.bat_careers"
    bowl_count_sql = f"SELECT COUNT(*) AS c FROM {f}.bowl_careers"
    bat_count_row = query_one(conn, bat_count_sql)
    bowl_count_row = query_one(conn, bowl_count_sql)
    bat_total = (bat_count_row or {}).get("c", 0) or 0
    bowl_total = (bowl_count_row or {}).get("c", 0) or 0

    if bat_total == 0 and bowl_total == 0:
        raise HTTPException(
            status_code=404,
            detail="No player data available for auto-fill",
        )

    exclude_ids: set[str] = set()
    if exclude:
        exclude_ids = {pid.strip() for pid in exclude.split(",") if pid.strip()}

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

    bat_where_parts = ["(is_provisional_bat = FALSE OR is_provisional_bat IS NULL)"]
    bowl_where_parts = ["(is_provisional_bowl = FALSE OR is_provisional_bowl IS NULL)"]
    bat_params: list[Any] = []
    bowl_params: list[Any] = []

    if strategy == "country" and country:
        bat_where_parts.append("LOWER(country) = LOWER(?)")
        bat_params.append(country)
        bowl_where_parts.append("LOWER(country) = LOWER(?)")
        bowl_params.append(country)

    if exclude_ids:
        bat_excl_ph = ", ".join(["?"] * len(exclude_ids))
        bowl_excl_ph = ", ".join(["?"] * len(exclude_ids))
        bat_where_parts.append(f"batter_id NOT IN ({bat_excl_ph})")
        bat_params.extend(sorted(exclude_ids))
        bowl_where_parts.append(f"bowler_id NOT IN ({bowl_excl_ph})")
        bowl_params.extend(sorted(exclude_ids))

    bat_where = " AND ".join(bat_where_parts)
    bowl_where = " AND ".join(bowl_where_parts)

    bat_rows_sorted = query_all(
        conn,
        f"SELECT * FROM {f}.bat_careers WHERE {bat_where} ORDER BY {bat_sort_col} DESC NULLS LAST LIMIT 50",
        bat_params,
    )
    bowl_rows_sorted = query_all(
        conn,
        f"SELECT * FROM {f}.bowl_careers WHERE {bowl_where} ORDER BY {bowl_sort_col} DESC NULLS LAST LIMIT 50",
        bowl_params,
    )

    if strategy == "bowl_heavy":
        max_bowlers, max_batters = 6, 5
    else:
        max_bowlers, max_batters = 5, 6

    selected_ids: set[str] = set()
    bowl_ids_ordered: list[str] = []

    if strategy == "balanced":
        bowl_ids_ordered = _pick_balanced_bowler_ids(
            bowl_rows_sorted, exclude_ids, max_bowlers
        )
        selected_ids.update(bowl_ids_ordered)
    else:
        for row in bowl_rows_sorted:
            if len(bowl_ids_ordered) >= max_bowlers:
                break
            bid = str(row.get("bowler_id", "") or "")
            if bid and bid not in selected_ids:
                selected_ids.add(bid)
                bowl_ids_ordered.append(bid)

    bat_ids_ordered: list[str] = []
    for row in bat_rows_sorted:
        if len(bat_ids_ordered) >= max_batters:
            break
        bid = str(row.get("batter_id", "") or "")
        if bid and bid not in selected_ids:
            selected_ids.add(bid)
            bat_ids_ordered.append(bid)

    if len(selected_ids) < 11:
        for row in bowl_rows_sorted:
            if len(selected_ids) >= 11:
                break
            bid = str(row.get("bowler_id", "") or "")
            if bid and bid not in selected_ids:
                selected_ids.add(bid)
                bowl_ids_ordered.append(bid)

    if strategy == "bat_heavy" and len(bat_ids_ordered) < max_batters:
        for row in bat_rows_sorted:
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
        db=(conn, fmt),
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
    db=Depends(_get_store),
):
    conn, fmt = db
    analysis_a = await analyse_team(ids=team_a, db=(conn, fmt))
    analysis_b = await analyse_team(ids=team_b, db=(conn, fmt))

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
