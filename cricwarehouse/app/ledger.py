"""Delivery clocks, resource state, and the player-event ledger.

Everything here is deterministic: no fitted model touches these columns, so the
output is reproducible from the source files alone and is what the golden-file
tests pin. The fitted values in `advanced.py` sit on top.

Three points cause most of the arithmetic bugs in ball-by-ball cricket models,
so they are separated explicitly:

* Three clocks, not one. A wide is not a ball of the over and not a ball faced;
  a no-ball is not a ball of the over but *is* a ball faced. One
  `legal_ball` variable cannot mean all three.
* Pre-delivery state. A delivery is valued by the state the bowler ran in to,
  never by a cumulative total that already contains the delivery's own outcome.
* Wickets in hand, not wickets down, and three separate counts of them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cricwarehouse.laws import (
    BATTER_CHARGED,
    BOWLER_CREDITED,
    FREE_HIT_IMPOSSIBLE,
    TEAM_WICKET,
    free_hit_is_approximate,
)

SET_OPPORTUNITIES = 8
DEFAULT_DEATH_OVER = 15


def _norm_kind(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower()


def attach_clocks(df: pd.DataFrame) -> pd.DataFrame:
    """Add the three clocks, the pre/post resource state, and wicket counts.

    Expects one row per delivery in source array order, grouped by
    (match_id, innings). Returns a copy.
    """
    df = df.copy()
    kind = _norm_kind(df["wicket_kind"])

    wide = df["is_wide"].fillna(False).to_numpy(dtype=bool)
    noball = df["is_noball"].fillna(False).to_numpy(dtype=bool)

    # A_t: every delivery record. The denominator for illegal-delivery rates.
    df["a_att"] = 1
    # L_t: valid for the over, so it advances the innings resource clock.
    df["l_valid"] = (~wide & ~noball).astype(np.int8)
    # F_t: a batter opportunity. No-balls count, wides do not.
    df["f_opp"] = (~wide).astype(np.int8)

    if "d_team" in df.columns and df["d_team"].notna().any():
        d_team = df["d_team"].fillna(0).to_numpy(dtype=np.int16)
        d_bat = df["d_bat"].fillna(0).to_numpy(dtype=np.int16)
        d_bowl = df["d_bowl"].fillna(0).to_numpy(dtype=np.int16)
    else:
        # Warehouses built before the attribution columns existed.
        d_team = kind.isin(TEAM_WICKET).to_numpy(dtype=np.int16)
        d_bat = kind.isin(BATTER_CHARGED).to_numpy(dtype=np.int16)
        d_bowl = kind.isin(BOWLER_CREDITED).to_numpy(dtype=np.int16)
    df["d_team"] = d_team
    df["d_bat"] = d_bat
    df["d_bowl"] = d_bowl

    grp = ["match_id", "innings"]
    g = df.groupby(grp, sort=False)

    # Pre-delivery: exclusive cumulative sums.
    df["u_before"] = g["l_valid"].cumsum() - df["l_valid"]
    df["runs_before"] = g["runs_total"].cumsum() - df["runs_total"].fillna(0)
    wkts_used = g["d_team"].cumsum() - df["d_team"]
    df["wkts_used"] = wkts_used

    sched = df["sched_balls"].to_numpy(dtype=float)
    df["b_before"] = np.clip(sched - df["u_before"].to_numpy(dtype=float), 0, None)
    df["b_after"] = np.clip(df["b_before"] - df["l_valid"], 0, None)
    # Wickets in hand. Ten for a full side, and the resource table's w axis.
    df["w_before"] = np.clip(10 - wkts_used, 0, 10)
    df["w_after"] = np.clip(df["w_before"] - df["d_team"], 0, 10)

    derived = _derive_free_hit(df)
    approx = np.array([free_hit_is_approximate(d) for d in df["start_date"]])
    df["fh_approx"] = approx
    # These dismissals cannot happen on a free hit. Where the flag was derived
    # rather than recorded, the dismissal is the stronger evidence: before the
    # 2015 law only some no-balls brought a free hit, so the inference was wrong
    # and the flag is withdrawn. Where the era did give a free hit to every
    # no-ball the record itself is inconsistent, so the flag stands and the
    # delivery is quarantined for review.
    impossible = kind.isin(FREE_HIT_IMPOSSIBLE).to_numpy()
    withdraw = derived & impossible & approx
    df["free_hit"] = derived & ~withdraw
    df["fh_withdrawn"] = withdraw
    df["fh_conflict"] = derived & impossible & ~approx

    df["over_valid"] = df["l_valid"].astype(bool)
    return df


def _derive_free_hit(df: pd.DataFrame) -> np.ndarray:
    """FH_t from the delivery stream.

    Cricsheet stores no free-hit flag, but the state is recoverable: the
    delivery after a no-ball is a free hit, and the entitlement survives an
    intervening wide because a wide is not a ball of the over.
    """
    noball = df["is_noball"].fillna(False).to_numpy(dtype=bool)
    valid = df["l_valid"].to_numpy(dtype=bool)
    # Innings boundaries reset the state.
    new_innings = np.empty(len(df), dtype=bool)
    if len(df):
        keys = list(zip(df["match_id"], df["innings"]))
        new_innings[0] = True
        for i in range(1, len(df)):
            new_innings[i] = keys[i] != keys[i - 1]

    out = np.zeros(len(df), dtype=bool)
    carry = False
    for i in range(len(df)):
        if new_innings[i]:
            carry = False
        out[i] = carry
        if noball[i]:
            carry = True
        elif not valid[i]:
            pass  # a wide does not consume the entitlement
        else:
            carry = False
    return out


def attach_chase_state(df: pd.DataFrame) -> pd.DataFrame:
    """Runs still required before each chase delivery.

    Cricsheet `target.runs` is the score required to win — one more than the
    first-innings total. Reading it as the first-innings total shifts every
    chase state by a run.
    """
    df = df.copy()
    target = df["target_runs"].to_numpy(dtype=float)
    need = np.where(
        np.isfinite(target) & (df["innings"].to_numpy() >= 2),
        np.maximum(target - df["runs_before"].to_numpy(dtype=float), 0.0),
        np.nan,
    )
    df["need_before"] = need
    df["need_after"] = np.maximum(need - df["runs_total"].fillna(0).to_numpy(dtype=float), 0.0)
    df["is_chase"] = np.isfinite(need)
    # Runs that count toward the target. A winning blow can overshoot by up to
    # five, and that overshoot is not chase value — it is unallocated.
    df["runs_capped"] = np.where(
        df["is_chase"], np.minimum(df["runs_total"].fillna(0), np.nan_to_num(need)), df["runs_total"].fillna(0)
    )
    return df


def attach_batter_state(df: pd.DataFrame) -> pd.DataFrame:
    """Batter opportunity count, set flag, batting position, and entry state."""
    df = df.copy()
    n = len(df)
    opp = np.zeros(n, dtype=np.int32)
    position = np.zeros(n, dtype=np.int16)
    entry_balls = np.zeros(n, dtype=np.int32)
    entry_wkts = np.zeros(n, dtype=np.int16)

    counts: dict[str, int] = {}
    order: dict[str, int] = {}
    entry: dict[str, tuple[int, int]] = {}
    key_prev = None

    strikers = df["striker"].to_numpy(dtype=object)
    nons = df["non_striker"].to_numpy(dtype=object)
    fopp = df["f_opp"].to_numpy(dtype=np.int8)
    u_before = df["u_before"].to_numpy(dtype=np.int32)
    wkts_used = df["wkts_used"].to_numpy(dtype=np.int16)
    keys = list(zip(df["match_id"], df["innings"]))

    for i in range(n):
        if keys[i] != key_prev:
            counts, order, entry = {}, {}, {}
            key_prev = keys[i]
        # Batting position is the order of first appearance at either end, so a
        # non-striker who never faces a ball still has a position.
        for who in (strikers[i], nons[i]):
            if who is not None and who == who and who not in order:
                order[who] = len(order) + 1
                entry[who] = (int(u_before[i]), int(wkts_used[i]))
        s = strikers[i]
        if s is not None and s == s:
            opp[i] = counts.get(s, 0)
            position[i] = order.get(s, 0)
            e = entry.get(s, (0, 0))
            entry_balls[i] = e[0]
            entry_wkts[i] = e[1]
            counts[s] = opp[i] + int(fopp[i])

    df["n_opp"] = opp
    df["is_set"] = opp >= SET_OPPORTUNITIES
    df["bat_position"] = position
    df["entry_balls"] = entry_balls
    df["entry_wkts"] = entry_wkts
    return df


def position_bucket(position: pd.Series) -> pd.Series:
    p = position.fillna(0).astype(int)
    return pd.Series(
        np.select(
            [p <= 0, p <= 2, p <= 4, p <= 6],
            ["unknown", "opener", "top middle", "lower middle"],
            default="lower order",
        ),
        index=position.index,
    )


def entry_role(entry_balls: pd.Series, entry_wkts: pd.Series, death_ball: int = 90) -> pd.Series:
    """Situation the batter walked into, evaluated in order."""
    ub = entry_balls.fillna(0).astype(int)
    kw = entry_wkts.fillna(0).astype(int)
    return pd.Series(
        np.select(
            [ub >= death_ball, (ub < 36) & (kw <= 1), (kw >= 3) & (ub < death_ball)],
            ["death entry", "early, wickets in hand", "rebuild"],
            default="other",
        ),
        index=entry_balls.index,
    )


def phase_label(df: pd.DataFrame) -> pd.Series:
    """Phase from the recorded powerplay where present, over number otherwise."""
    over = df["over"].fillna(0).astype(int)
    death_over = np.where(
        df["sched_overs"].fillna(20) >= 20, DEFAULT_DEATH_OVER, (df["sched_overs"].fillna(20) * 0.75).round()
    )
    recorded = df.get("is_powerplay")
    if recorded is not None and df.get("recorded_powerplay") is not None:
        pp = np.where(
            df["recorded_powerplay"].fillna(False).to_numpy(dtype=bool),
            recorded.fillna(False).to_numpy(dtype=bool),
            (over < 6).to_numpy(),
        )
    else:
        pp = (over < 6).to_numpy()
    return pd.Series(
        np.select([pp, over < death_over], ["powerplay", "middle"], default="death"),
        index=df.index,
    )


def pressure_band(df: pd.DataFrame) -> pd.Series:
    """Target-pressure band for chases: required rate against balls remaining."""
    need = df["need_before"].to_numpy(dtype=float)
    b = np.maximum(df["b_before"].to_numpy(dtype=float), 1.0)
    rr = need / b * 6.0
    return pd.Series(
        np.select(
            [~np.isfinite(rr), rr < 6, rr < 8, rr < 10, rr < 13],
            ["first innings", "under 6", "6 to 8", "8 to 10", "10 to 13"],
            default="13 plus",
        ),
        index=df.index,
    )


def player_events(df: pd.DataFrame) -> pd.DataFrame:
    """Explode deliveries into the player-event ledger of Section 4.4.

    One delivery can create several events. The striker's run-and-clock value
    and the dismissed player's wicket charge are separate rows, which is the
    only way a non-striker run-out lands on the right player.
    """
    rows: list[pd.DataFrame] = []

    striker = df[df["striker"].notna()]
    rows.append(
        pd.DataFrame(
            {
                "match_id": striker["match_id"].to_numpy(),
                "innings": striker["innings"].to_numpy(),
                "delivery_index": striker.index.to_numpy(),
                "event": "bat_run_clock",
                "person_id": striker["striker"].to_numpy(),
                "value": striker["v_bat_run_clock"].to_numpy(),
                "exposure": striker["f_opp"].to_numpy(),
            }
        )
    )

    charged = df[(df["d_bat"] > 0) & df["player_out"].notna()]
    rows.append(
        pd.DataFrame(
            {
                "match_id": charged["match_id"].to_numpy(),
                "innings": charged["innings"].to_numpy(),
                "delivery_index": charged.index.to_numpy(),
                "event": "bat_dismissal",
                "person_id": charged["player_out"].to_numpy(),
                "value": charged["w_bat"].to_numpy(),
                # A dismissal is not a ball faced, so it earns no replacement
                # debit of its own.
                "exposure": 0,
            }
        )
    )

    bowler = df[df["bowler"].notna()]
    rows.append(
        pd.DataFrame(
            {
                "match_id": bowler["match_id"].to_numpy(),
                "innings": bowler["innings"].to_numpy(),
                "delivery_index": bowler.index.to_numpy(),
                "event": "bowl_run_clock",
                "person_id": bowler["bowler"].to_numpy(),
                "value": bowler["v_bowl_run_clock"].to_numpy(),
                "exposure": bowler["l_valid"].to_numpy(),
            }
        )
    )
    credited = df[(df["d_bowl"] > 0) & df["bowler"].notna()]
    rows.append(
        pd.DataFrame(
            {
                "match_id": credited["match_id"].to_numpy(),
                "innings": credited["innings"].to_numpy(),
                "delivery_index": credited.index.to_numpy(),
                "event": "bowl_wicket",
                "person_id": credited["bowler"].to_numpy(),
                "value": -credited["w_bowl"].to_numpy(),
                "exposure": 0,
            }
        )
    )

    unalloc = df[df["unallocated"].abs() > 1e-9]
    rows.append(
        pd.DataFrame(
            {
                "match_id": unalloc["match_id"].to_numpy(),
                "innings": unalloc["innings"].to_numpy(),
                "delivery_index": unalloc.index.to_numpy(),
                "event": "unallocated",
                "person_id": None,
                "value": unalloc["unallocated"].to_numpy(),
                "exposure": 0,
            }
        )
    )
    return pd.concat(rows, ignore_index=True)
