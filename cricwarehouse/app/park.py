"""Park factors for the stat-line shift card.

Cricsheet does not record grass, dew, or a referee's pitch rating. What we
observe is a venue × competition × gender × season-window × innings-role cell.
That is a park factor, not a soil model.

Leave the scored match out of φ. Shrink thin grounds toward the competition
mean. Refuse the number when the cell is still too small after removal.

v1 ships venue × competition × rolling window × set/chase. Phase splits,
toss, and opposition quality wait until residuals still scream.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

from cricwarehouse.competitions import T20_METRICS

# ~5 T20 innings of prior strength; Tests need more balls to move φ off 1.
N0_BALLS = {"t20": 600, "odi": 900, "test": 1800}
N_MIN_INNINGS = {"t20": 4, "odi": 4, "test": 4}
WINDOW_DAYS = {"t20": 730, "odi": 1095, "test": 1825}
# Average is runs per dismissal. A handful of outs in the without-sample
# swings it wildly, so the card only prints an expected average past this.
AVG_OUTS_FLOOR = {"t20": 8, "odi": 8, "test": 10**9}
# Enough teammate balls away from this venue to prefer talent over league.
TALENT_BALLS_FLOOR = {"t20": 60, "odi": 90, "test": 120}
# Share of teammate balls that must sit in a usable cell before we print φ.
COVERAGE_FLOOR = 0.5
MIN_USED_BALLS = {"t20": 60, "odi": 90, "test": 120}

T20_COMPS = frozenset(T20_METRICS)


def family_of(competition: str | None) -> str:
    if competition in T20_COMPS:
        return "t20"
    if competition == "odi":
        return "odi"
    return "test"


def innings_role(target_runs: Any, innings: Any, competition: str | None) -> str | None:
    """Set vs chase. Fourth-innings Test rates are not a first-innings factor."""
    if family_of(competition) == "test":
        try:
            if int(innings) not in (1, 2):
                return None
        except (TypeError, ValueError):
            return None
    return "chase" if target_runs is not None else "set"


def parse_date(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, date):
        return value.toordinal()
    text = str(value)[:10]
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10])).toordinal()
    except (TypeError, ValueError):
        return 0


def shrink_phi(phi: float, n: float, n0: float) -> float:
    """Empirical Bayes toward a park factor of 1 (competition mean)."""
    if n0 <= 0:
        return phi
    weight = n / (n + n0)
    return weight * phi + (1.0 - weight) * 1.0


def loo_rate(cell_num: float, cell_den: float, own_num: float, own_den: float) -> float | None:
    den = cell_den - own_den
    if den <= 0:
        return None
    return (cell_num - own_num) / den


def expected_sr(lambda_r: float, phi_r: float) -> float:
    return 100.0 * lambda_r * phi_r


def expected_econ(lambda_r: float, phi_r: float) -> float:
    return 6.0 * lambda_r * phi_r


def expected_avg(lambda_r: float, phi_r: float, lambda_w: float, phi_w: float) -> float | None:
    den = lambda_w * phi_w
    if den <= 0:
        return None
    return (lambda_r * phi_r) / den


def _round(value: float | None, places: int) -> float | None:
    if value is None:
        return None
    return round(float(value), places)


def _n(value: Any, default: int = 0) -> int:
    try:
        if value is None or value != value:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class EnvRow:
    match_id: str
    date: int
    venue: str
    competition: str
    gender: str
    role: str
    balls: int
    runs: int
    wickets: int


@dataclass
class Totals:
    balls: int = 0
    runs: int = 0
    wickets: int = 0
    n_innings: int = 0


@dataclass
class MatchLine:
    match_id: str
    innings: int
    date: int
    venue: str
    competition: str
    gender: str
    role: str | None
    balls: int
    runs: int
    wickets: int


@dataclass
class CellIndex:
    groups: dict[tuple[str, str, str, str], list[EnvRow]] = field(default_factory=dict)

    @classmethod
    def from_rows(cls, rows: Iterable[EnvRow]) -> CellIndex:
        groups: dict[tuple[str, str, str, str], list[EnvRow]] = defaultdict(list)
        for row in rows:
            groups[(row.venue, row.competition, row.gender, row.role)].append(row)
            groups[("", row.competition, row.gender, row.role)].append(row)
        for bucket in groups.values():
            bucket.sort(key=lambda r: r.date)
        return cls(groups=dict(groups))

    def window(self, key: tuple[str, str, str, str], day: int, window_days: int, exclude_match: str) -> Totals:
        rows = self.groups.get(key) or []
        if not rows:
            return Totals()
        dates = [r.date for r in rows]
        lo = bisect_left(dates, day - window_days)
        hi = bisect_right(dates, day)
        out = Totals()
        for row in rows[lo:hi]:
            if row.match_id == exclude_match:
                continue
            out.balls += row.balls
            out.runs += row.runs
            out.wickets += row.wickets
            out.n_innings += 1
        return out


@dataclass
class TalentIndex:
    lines: list[MatchLine]

    def __post_init__(self) -> None:
        self._by_comp: dict[tuple[str, str], list[MatchLine]] = defaultdict(list)
        for line in self.lines:
            self._by_comp[(line.competition, line.gender)].append(line)
        for bucket in self._by_comp.values():
            bucket.sort(key=lambda r: r.date)

    def rate(self, line: MatchLine, window_days: int, floor: int) -> tuple[float | None, float | None]:
        """Teammate run and wicket rates away from this venue, same competition-window."""
        rows = self._by_comp.get((line.competition, line.gender)) or []
        if not rows:
            return None, None
        dates = [r.date for r in rows]
        lo = bisect_left(dates, line.date - window_days)
        hi = bisect_right(dates, line.date)
        balls = runs = wickets = 0
        for row in rows[lo:hi]:
            if row.venue == line.venue:
                continue
            balls += row.balls
            runs += row.runs
            wickets += row.wickets
        if balls < floor:
            return None, None
        return runs / balls, wickets / balls


@dataclass
class Expectation:
    expected_sr: float | None
    expected_econ: float | None
    expected_avg: float | None
    phi_r: float | None
    phi_w: float | None
    used_balls: int
    total_balls: int
    used_matches: int
    thin_matches: int
    n_cell_innings: int
    coverage: float
    ok: bool
    reason: str | None


def park_factor(
    cell: Totals,
    league: Totals,
    *,
    n0: float,
    n_min: int,
) -> tuple[float, float, str | None]:
    """Return (φ_r, φ_w, refuse_reason)."""
    if cell.n_innings < n_min or cell.balls <= 0:
        return 1.0, 1.0, "too few matches at these grounds to adjust for pitch"
    if league.balls <= 0 or league.runs <= 0:
        return 1.0, 1.0, "too few matches at these grounds to adjust for pitch"
    mu_r = cell.runs / cell.balls
    lam0_r = league.runs / league.balls
    phi_r = shrink_phi(mu_r / lam0_r, cell.balls, n0)
    if cell.wickets > 0 and league.wickets > 0:
        mu_w = cell.wickets / cell.balls
        lam0_w = league.wickets / league.balls
        phi_w = shrink_phi(mu_w / lam0_w, cell.balls, n0)
    else:
        phi_w = 1.0
    return phi_r, phi_w, None


def expect_lines(lines: list[MatchLine], match_ids: set[str], env: CellIndex, talent: TalentIndex) -> Expectation:
    """Balls-weighted E[rate | schedule] for the teammate lines in `match_ids`."""
    exp_runs = 0.0
    exp_wkts = 0.0
    phi_r_w = 0.0
    phi_w_w = 0.0
    cell_innings = 0
    used_balls = 0
    total_balls = 0
    used_matches: set[str] = set()
    thin_matches: set[str] = set()
    family_used = "t20"

    for line in lines:
        if line.match_id not in match_ids:
            continue
        total_balls += line.balls
        if line.balls <= 0 or not line.role:
            continue
        family = family_of(line.competition)
        family_used = family
        window = WINDOW_DAYS[family]
        n0 = N0_BALLS[family]
        n_min = N_MIN_INNINGS[family]
        cell = env.window(
            (line.venue, line.competition, line.gender, line.role),
            line.date,
            window,
            line.match_id,
        )
        league = env.window(
            ("", line.competition, line.gender, line.role),
            line.date,
            window,
            line.match_id,
        )
        phi_r, phi_w, reason = park_factor(cell, league, n0=n0, n_min=n_min)
        if reason:
            thin_matches.add(line.match_id)
            continue
        lam_r, lam_w = talent.rate(line, window, TALENT_BALLS_FLOOR[family])
        if lam_r is None:
            lam_r = league.runs / league.balls
        if lam_w is None:
            lam_w = league.wickets / league.balls if league.balls else 0.0
        exp_runs += line.balls * lam_r * phi_r
        exp_wkts += line.balls * lam_w * phi_w
        phi_r_w += phi_r * line.balls
        phi_w_w += phi_w * line.balls
        used_balls += line.balls
        used_matches.add(line.match_id)
        cell_innings += cell.n_innings

    coverage = (used_balls / total_balls) if total_balls else 0.0
    min_balls = MIN_USED_BALLS[family_used]
    if used_balls < min_balls or coverage < COVERAGE_FLOOR:
        return Expectation(
            expected_sr=None,
            expected_econ=None,
            expected_avg=None,
            phi_r=None,
            phi_w=None,
            used_balls=used_balls,
            total_balls=total_balls,
            used_matches=len(used_matches),
            thin_matches=len(thin_matches),
            n_cell_innings=cell_innings,
            coverage=coverage,
            ok=False,
            reason="too few matches at these grounds to adjust for pitch",
        )
    return Expectation(
        expected_sr=100.0 * exp_runs / used_balls,
        expected_econ=6.0 * exp_runs / used_balls,
        expected_avg=(exp_runs / exp_wkts) if exp_wkts > 0 else None,
        phi_r=phi_r_w / used_balls,
        phi_w=phi_w_w / used_balls,
        used_balls=used_balls,
        total_balls=total_balls,
        used_matches=len(used_matches),
        thin_matches=len(thin_matches),
        n_cell_innings=cell_innings,
        coverage=coverage,
        ok=True,
        reason=None,
    )


def _residual(actual: float | None, expected: float | None, places: int) -> float | None:
    if actual is None or expected is None:
        return None
    return _round(actual - expected, places)


def _delta(a: float | None, b: float | None, places: int) -> float | None:
    if a is None or b is None:
        return None
    return _round(a - b, places)


def _apply_side(
    pack: dict[str, Any], side: str, exp: Expectation, *, kind: str, outs: int, family: str
) -> None:
    show_avg = outs >= AVG_OUTS_FLOOR.get(family, 8) and exp.expected_avg is not None
    if kind == "bat":
        pack[f"sr_exp_{side}"] = _round(exp.expected_sr, 1) if exp.ok else None
        pack[f"avg_exp_{side}"] = _round(exp.expected_avg, 1) if exp.ok and show_avg else None
        pack[f"sr_resid_{side}"] = _residual(pack.get(f"sr_{side}"), pack.get(f"sr_exp_{side}"), 1)
        pack[f"avg_resid_{side}"] = _residual(pack.get(f"avg_{side}"), pack.get(f"avg_exp_{side}"), 1)
    else:
        pack[f"econ_exp_{side}"] = _round(exp.expected_econ, 2) if exp.ok else None
        pack[f"avg_exp_{side}"] = _round(exp.expected_avg, 1) if exp.ok and show_avg else None
        pack[f"econ_resid_{side}"] = _residual(pack.get(f"econ_{side}"), pack.get(f"econ_exp_{side}"), 2)
        pack[f"avg_resid_{side}"] = _residual(pack.get(f"avg_{side}"), pack.get(f"avg_exp_{side}"), 1)
    pack[f"phi_r_{side}"] = _round(exp.phi_r, 3) if exp.ok else None
    pack[f"pitch_ok_{side}"] = exp.ok
    pack[f"pitch_coverage_{side}"] = _round(exp.coverage, 2)
    pack[f"pitch_reason_{side}"] = None if exp.ok else exp.reason


def attach_pitch(
    split: dict[str, Any],
    bat_lines: list[MatchLine],
    bowl_lines: list[MatchLine],
    with_ids: set[str],
    match_ids: Iterable[str],
    env: CellIndex,
) -> dict[str, Any]:
    """Add pitch-expected lines and residual deltas onto a with/without split."""
    ids = set(match_ids)
    with_set = {m for m in with_ids if m in ids}
    wo_set = {m for m in ids if m not in with_ids}
    sample = next((ln for ln in bat_lines + bowl_lines if ln.match_id in ids), None)
    family = family_of(sample.competition) if sample else "t20"
    talent_bat = TalentIndex(bat_lines)
    talent_bowl = TalentIndex(bowl_lines)
    bat = split.setdefault("bat", {})
    bowl = split.setdefault("bowl", {})

    bat_with = expect_lines(bat_lines, with_set, env, talent_bat) if with_set else None
    bat_wo = expect_lines(bat_lines, wo_set, env, talent_bat) if wo_set else None
    bowl_with = expect_lines(bowl_lines, with_set, env, talent_bowl) if with_set else None
    bowl_wo = expect_lines(bowl_lines, wo_set, env, talent_bowl) if wo_set else None

    if bat_with:
        _apply_side(bat, "with", bat_with, kind="bat", outs=_n(bat.get("outs_with")), family=family)
    if bat_wo:
        _apply_side(bat, "wo", bat_wo, kind="bat", outs=_n(bat.get("outs_wo")), family=family)
    if bowl_with:
        _apply_side(bowl, "with", bowl_with, kind="bowl", outs=_n(bowl.get("wk_with")), family=family)
    if bowl_wo:
        _apply_side(bowl, "wo", bowl_wo, kind="bowl", outs=_n(bowl.get("wk_wo")), family=family)

    bat["sr_delta_adj"] = _delta(bat.get("sr_resid_with"), bat.get("sr_resid_wo"), 1)
    bat["avg_delta_adj"] = _delta(bat.get("avg_resid_with"), bat.get("avg_resid_wo"), 1)
    bowl["econ_delta_adj"] = _delta(bowl.get("econ_resid_with"), bowl.get("econ_resid_wo"), 2)
    bowl["avg_delta_adj"] = _delta(bowl.get("avg_resid_with"), bowl.get("avg_resid_wo"), 1)

    with_ok = bool((bat_with and bat_with.ok) or (bowl_with and bowl_with.ok))
    wo_ok = bool((bat_wo and bat_wo.ok) or (bowl_wo and bowl_wo.ok))
    reason = None
    if not with_ok:
        reason = (bat_with or bowl_with).reason if (bat_with or bowl_with) else "too few matches at these grounds to adjust for pitch"
    split["pitch"] = {
        "ok_with": with_ok,
        "ok_wo": wo_ok,
        "ok_adj": with_ok and wo_ok,
        "reason": reason,
        "coverage_with": _round(
            ((bat_with.coverage if bat_with else 0) + (bowl_with.coverage if bowl_with else 0))
            / max(int(bat_with is not None) + int(bowl_with is not None), 1),
            2,
        ),
    }
    return split


def _row_env(row: Any) -> EnvRow | None:
    role = innings_role(row[6], row[1], row[3])
    if not role:
        return None
    balls = _n(row[7])
    if balls <= 0:
        return None
    return EnvRow(
        match_id=str(row[0]),
        date=parse_date(row[5]),
        venue=str(row[2] or ""),
        competition=str(row[3] or ""),
        gender=str(row[4] or ""),
        role=role,
        balls=balls,
        runs=_n(row[8]),
        wickets=_n(row[9]),
    )


def load_environment(con, comps: list[str] | None, gender: str | None) -> CellIndex:
    where = ["i.innings_kind = 'regular'", "(m.competition <> 'test' OR i.innings IN (1, 2))"]
    params: list[Any] = []
    if comps:
        ph = ",".join(["?"] * len(comps))
        where.append(f"m.competition IN ({ph})")
        params.extend(comps)
    if gender:
        where.append("m.gender = ?")
        params.append(gender)
    recs = con.execute(
        f"""
        SELECT i.match_id, i.innings, m.venue, m.competition, m.gender, m.start_date,
               i.target_runs, i.legal_balls,
               COALESCE(i.delivery_runs, i.runs) AS runs, i.wickets
        FROM innings i
        JOIN matches m ON m.match_id = i.match_id
        WHERE {' AND '.join(where)}
        """,
        params,
    ).fetchall()
    rows = []
    for rec in recs or []:
        item = _row_env(rec)
        if item:
            rows.append(item)
    return CellIndex.from_rows(rows)


def load_teammate_lines(
    con,
    pid: str,
    team: str,
    match_ids: list[str],
) -> tuple[list[MatchLine], list[MatchLine]]:
    if not match_ids:
        return [], []
    ph = ",".join(["?"] * len(match_ids))
    bat = con.execute(
        f"""
        SELECT b.match_id, b.innings, m.start_date, m.venue, m.competition, m.gender,
               i.target_runs,
               SUM(b.runs), SUM(b.balls),
               SUM(CASE WHEN NOT b.not_out THEN 1 ELSE 0 END)
        FROM batting_lines b
        JOIN xi x ON x.match_id = b.match_id AND x.person_id = b.person_id AND x.team = ?
        JOIN matches m ON m.match_id = b.match_id
        JOIN innings i ON i.match_id = b.match_id AND i.innings = b.innings
        WHERE b.person_id <> ? AND b.innings_kind = 'regular' AND b.match_id IN ({ph})
        GROUP BY 1, 2, 3, 4, 5, 6, 7
        """,
        [team, pid] + match_ids,
    ).fetchall()
    bowl = con.execute(
        f"""
        SELECT bl.match_id, bl.innings, m.start_date, m.venue, m.competition, m.gender,
               i.target_runs,
               SUM(bl.runs), SUM(bl.legal_balls), SUM(bl.wickets)
        FROM bowling_lines bl
        JOIN xi x ON x.match_id = bl.match_id AND x.person_id = bl.person_id AND x.team = ?
        JOIN matches m ON m.match_id = bl.match_id
        JOIN innings i ON i.match_id = bl.match_id AND i.innings = bl.innings
        WHERE bl.person_id <> ? AND bl.innings_kind = 'regular' AND bl.match_id IN ({ph})
        GROUP BY 1, 2, 3, 4, 5, 6, 7
        """,
        [team, pid] + match_ids,
    ).fetchall()

    def to_lines(recs) -> list[MatchLine]:
        out = []
        for r in recs or []:
            balls = _n(r[8])
            if balls <= 0:
                continue
            out.append(
                MatchLine(
                    match_id=str(r[0]),
                    innings=_n(r[1]),
                    date=parse_date(r[2]),
                    venue=str(r[3] or ""),
                    competition=str(r[4] or ""),
                    gender=str(r[5] or ""),
                    role=innings_role(r[6], r[1], r[4]),
                    runs=_n(r[7]),
                    balls=balls,
                    wickets=_n(r[9]),
                )
            )
        return out

    return to_lines(bat), to_lines(bowl)
