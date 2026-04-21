"""Expected remaining runs: the resource tables R(b, w) and R2(b, w, need).

R is the target-neutral first-innings table. R2 is the chase table, which the
first table cannot stand in for: a chase ends at the target, so a wicket with
the run rate comfortably ahead costs far less than a target-neutral table says.
About half of all player deliveries happen in chases, so the distortion is not
a footnote.

Fitting follows one fixed recipe so a rebuild reproduces the same numbers:

1. Raw cell means with visit counts on the boundary-inclusive grid.
2. A separable Gaussian smooth, count-weighted, to borrow strength across
   neighbouring states.
3. Projection onto the shape constraints by weighted least squares, using
   cyclic pool-adjacent-violators along each axis.

The grid is (B+1) x 11, not B x 10: zero balls left and zero wickets in hand are
real states, and they are the states that anchor the whole table at zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

STANDARD_BALLS = 120
MAX_WICKETS = 10
# Chase `need` is coarser than the ball clock because the dimension is much
# sparser. Values between grid points are interpolated.
NEED_STEP = 3
NEED_MAX = 258
PROJECTION_CYCLES = 14
# Weight given to an unvisited cell so the projection stays defined everywhere
# without letting empty states pull the fitted surface around.
PRIOR_WEIGHT = 0.25
SMOOTH_BANDWIDTH_BALLS = 3.5
SMOOTH_BANDWIDTH_WICKETS = 0.75
SMOOTH_BANDWIDTH_NEED = 1.5
VENUE_PRIOR_INNINGS = 20
ERA_YEARS = 4


def isotonic(y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Weighted least-squares projection onto the non-decreasing cone.

    Pool adjacent violators: walk left to right, and whenever a block's level
    sits below its predecessor's, merge the two and take their weighted mean.
    """
    n = len(y)
    if n < 2:
        return y.astype(float).copy()
    level = np.empty(n, dtype=float)
    weight = np.empty(n, dtype=float)
    size = np.empty(n, dtype=np.int64)
    top = -1
    for i in range(n):
        top += 1
        level[top] = y[i]
        weight[top] = w[i]
        size[top] = 1
        while top > 0 and level[top - 1] > level[top]:
            wsum = weight[top - 1] + weight[top]
            if wsum <= 0:
                level[top - 1] = 0.5 * (level[top - 1] + level[top])
            else:
                level[top - 1] = (
                    level[top - 1] * weight[top - 1] + level[top] * weight[top]
                ) / wsum
            weight[top - 1] = wsum
            size[top - 1] += size[top]
            top -= 1
    out = np.empty(n, dtype=float)
    pos = 0
    for b in range(top + 1):
        out[pos : pos + size[b]] = level[b]
        pos += size[b]
    return out


def _isotonic_along(values: np.ndarray, weights: np.ndarray, axis: int) -> np.ndarray:
    """Apply `isotonic` to every 1-D chain along one axis."""
    v = np.moveaxis(values, axis, 0)
    w = np.moveaxis(weights, axis, 0)
    shape = v.shape
    v2 = v.reshape(shape[0], -1).copy()
    w2 = w.reshape(shape[0], -1)
    for j in range(v2.shape[1]):
        col = v2[:, j]
        if col[0] <= col[-1] and np.all(np.diff(col) >= -1e-12):
            continue
        v2[:, j] = isotonic(col, w2[:, j])
    return np.moveaxis(v2.reshape(shape), 0, axis)


def _gaussian_kernel(n: int, bandwidth: float) -> np.ndarray:
    idx = np.arange(n, dtype=float)
    d = idx[:, None] - idx[None, :]
    k = np.exp(-0.5 * (d / max(bandwidth, 1e-6)) ** 2)
    return k


def _smooth(raw: np.ndarray, counts: np.ndarray, bandwidths: tuple[float, ...]) -> np.ndarray:
    """Count-weighted Nadaraya-Watson smooth, applied separably per axis."""
    num = raw * counts
    den = counts.astype(float).copy()
    for axis, bw in enumerate(bandwidths):
        k = _gaussian_kernel(raw.shape[axis], bw)
        num = np.moveaxis(np.tensordot(k, np.moveaxis(num, axis, 0), axes=(1, 0)), 0, axis)
        den = np.moveaxis(np.tensordot(k, np.moveaxis(den, axis, 0), axes=(1, 0)), 0, axis)
    out = np.where(den > 1e-9, num / np.maximum(den, 1e-9), 0.0)
    return out


@dataclass
class ResourceTable:
    """Fitted R(b, w) for one sex, plus its environment adjustments."""

    grid: np.ndarray  # (B+1, 11)
    counts: np.ndarray
    balls: int = STANDARD_BALLS
    competition: dict[str, float] = field(default_factory=dict)
    era: dict[str, float] = field(default_factory=dict)
    venue: dict[str, float] = field(default_factory=dict)

    def base(self, b: np.ndarray, w: np.ndarray) -> np.ndarray:
        bi = np.clip(np.rint(np.nan_to_num(b)), 0, self.balls).astype(np.int32)
        wi = np.clip(np.rint(np.nan_to_num(w)), 0, MAX_WICKETS).astype(np.int32)
        return self.grid[bi, wi]

    def share(self, b: np.ndarray, w: np.ndarray) -> np.ndarray:
        """Remaining-resource share, so an environment effect vanishes at the end.

        Without this an adjustment would still be revaluing an innings that has
        no balls and no wickets left to play with.
        """
        full = self.grid[self.balls, MAX_WICKETS]
        if full <= 0:
            return np.zeros_like(np.asarray(b, dtype=float))
        return self.base(b, w) / full

    def offset(
        self, competition: np.ndarray, era: np.ndarray, venue: np.ndarray
    ) -> np.ndarray:
        c = np.array([self.competition.get(x, 0.0) for x in competition], dtype=float)
        e = np.array([self.era.get(x, 0.0) for x in era], dtype=float)
        v = np.array([self.venue.get(x, 0.0) for x in venue], dtype=float)
        return c + e + v

    def value(
        self,
        b: np.ndarray,
        w: np.ndarray,
        competition: np.ndarray | None = None,
        era: np.ndarray | None = None,
        venue: np.ndarray | None = None,
    ) -> np.ndarray:
        out = self.base(b, w)
        if competition is not None:
            out = out + self.share(b, w) * self.offset(competition, era, venue)
        # Reapply the boundaries after the environment tilt.
        zero = (np.nan_to_num(b) <= 0) | (np.nan_to_num(w) <= 0)
        return np.where(zero, 0.0, np.maximum(out, 0.0))

    def as_rows(self, sex: str) -> list[dict]:
        rows = []
        for bi in range(self.grid.shape[0]):
            for wi in range(self.grid.shape[1]):
                rows.append(
                    {
                        "sex": sex,
                        "balls_remaining": bi,
                        "wickets_in_hand": wi,
                        "expected_runs": round(float(self.grid[bi, wi]), 3),
                        "n": int(self.counts[bi, wi]),
                    }
                )
        return rows


@dataclass
class ChaseTable:
    """Fitted R2(b, w, need) for one sex."""

    grid: np.ndarray  # (B+1, 11, n_need)
    counts: np.ndarray
    balls: int = STANDARD_BALLS
    need_step: int = NEED_STEP
    linked: bool = False  # True when a thin pool fell back to a linked estimate

    def value(self, b: np.ndarray, w: np.ndarray, need: np.ndarray) -> np.ndarray:
        bi = np.clip(np.rint(np.nan_to_num(b)), 0, self.balls).astype(np.int32)
        wi = np.clip(np.rint(np.nan_to_num(w)), 0, MAX_WICKETS).astype(np.int32)
        nd = np.clip(np.nan_to_num(need), 0, self.grid.shape[2] * self.need_step - 1)
        pos = nd / self.need_step
        lo = np.clip(np.floor(pos), 0, self.grid.shape[2] - 1).astype(np.int32)
        hi = np.clip(lo + 1, 0, self.grid.shape[2] - 1)
        frac = pos - lo
        out = self.grid[bi, wi, lo] * (1 - frac) + self.grid[bi, wi, hi] * frac
        # A chase cannot be worth more than the runs it still needs, and runs out
        # of balls or wickets are worth nothing.
        out = np.minimum(out, nd)
        zero = (np.nan_to_num(b) <= 0) | (np.nan_to_num(w) <= 0) | (nd <= 0)
        return np.where(zero, 0.0, np.maximum(out, 0.0))

    def as_rows(self, sex: str, need_values: tuple[int, ...]) -> list[dict]:
        rows = []
        for need in need_values:
            k = int(round(need / self.need_step))
            if k >= self.grid.shape[2]:
                continue
            for bi in range(0, self.grid.shape[0]):
                for wi in range(self.grid.shape[1]):
                    rows.append(
                        {
                            "sex": sex,
                            "need": int(need),
                            "balls_remaining": bi,
                            "wickets_in_hand": wi,
                            "expected_runs": round(float(self.grid[bi, wi, k]), 3),
                            "n": int(self.counts[bi, wi, k]),
                        }
                    )
        return rows


def _raw_cells(
    b: np.ndarray, w: np.ndarray, y: np.ndarray, shape: tuple[int, int]
) -> tuple[np.ndarray, np.ndarray]:
    bi = np.clip(b.astype(np.int64), 0, shape[0] - 1)
    wi = np.clip(w.astype(np.int64), 0, shape[1] - 1)
    flat = bi * shape[1] + wi
    n = np.bincount(flat, minlength=shape[0] * shape[1]).reshape(shape)
    s = np.bincount(flat, weights=y, minlength=shape[0] * shape[1]).reshape(shape)
    mean = np.where(n > 0, s / np.maximum(n, 1), 0.0)
    return mean, n


def fit_resource_table(
    b: np.ndarray,
    w: np.ndarray,
    y: np.ndarray,
    *,
    balls: int = STANDARD_BALLS,
) -> ResourceTable:
    shape = (balls + 1, MAX_WICKETS + 1)
    raw, counts = _raw_cells(b, w, y, shape)
    smooth = _smooth(raw, counts, (SMOOTH_BANDWIDTH_BALLS, SMOOTH_BANDWIDTH_WICKETS))
    weights = counts.astype(float) + PRIOR_WEIGHT
    grid = _project_2d(smooth, weights)
    return ResourceTable(grid=grid, counts=counts, balls=balls)


def _apply_boundaries_2d(grid: np.ndarray) -> np.ndarray:
    grid = np.maximum(grid, 0.0)
    grid[0, :] = 0.0
    grid[:, 0] = 0.0
    return grid


def _project_2d(smooth: np.ndarray, weights: np.ndarray) -> np.ndarray:
    grid = _apply_boundaries_2d(smooth.copy())
    for _ in range(PROJECTION_CYCLES):
        before = grid.copy()
        grid = _isotonic_along(grid, weights, axis=0)
        grid = _isotonic_along(grid, weights, axis=1)
        grid = _apply_boundaries_2d(grid)
        if np.max(np.abs(grid - before)) < 1e-6:
            break
    # Cycling projections onto two monotone cones leaves float-level violations
    # of whichever constraint was not applied last. A running maximum closes
    # them exactly, at a cost of well under a hundredth of a run.
    grid = np.maximum.accumulate(grid, axis=0)
    grid = np.maximum.accumulate(grid, axis=1)
    return _apply_boundaries_2d(grid)


def fit_chase_table(
    b: np.ndarray,
    w: np.ndarray,
    need: np.ndarray,
    y: np.ndarray,
    *,
    balls: int = STANDARD_BALLS,
    need_step: int = NEED_STEP,
    need_max: int = NEED_MAX,
) -> ChaseTable:
    n_need = need_max // need_step + 1
    shape = (balls + 1, MAX_WICKETS + 1, n_need)
    bi = np.clip(b.astype(np.int64), 0, shape[0] - 1)
    wi = np.clip(w.astype(np.int64), 0, shape[1] - 1)
    ni = np.clip(np.rint(need / need_step).astype(np.int64), 0, shape[2] - 1)
    flat = (bi * shape[1] + wi) * shape[2] + ni
    size = shape[0] * shape[1] * shape[2]
    counts = np.bincount(flat, minlength=size).reshape(shape)
    sums = np.bincount(flat, weights=y, minlength=size).reshape(shape)
    raw = np.where(counts > 0, sums / np.maximum(counts, 1), 0.0)
    smooth = _smooth(
        raw,
        counts,
        (SMOOTH_BANDWIDTH_BALLS, SMOOTH_BANDWIDTH_WICKETS, SMOOTH_BANDWIDTH_NEED),
    )
    weights = counts.astype(float) + PRIOR_WEIGHT
    need_axis = np.arange(n_need, dtype=float) * need_step
    grid = _project_3d(smooth, weights, need_axis)
    return ChaseTable(grid=grid, counts=counts, balls=balls, need_step=need_step)


def _apply_boundaries_3d(grid: np.ndarray, need_axis: np.ndarray) -> np.ndarray:
    grid = np.maximum(grid, 0.0)
    grid = np.minimum(grid, need_axis[None, None, :])
    grid[0, :, :] = 0.0
    grid[:, 0, :] = 0.0
    grid[:, :, 0] = 0.0
    return grid


def _project_3d(
    smooth: np.ndarray, weights: np.ndarray, need_axis: np.ndarray
) -> np.ndarray:
    grid = _apply_boundaries_3d(smooth.copy(), need_axis)
    for _ in range(PROJECTION_CYCLES):
        before = grid.copy()
        for axis in (0, 1, 2):
            grid = _isotonic_along(grid, weights, axis=axis)
        grid = _apply_boundaries_3d(grid, need_axis)
        if np.max(np.abs(grid - before)) < 1e-6:
            break
    for axis in (0, 1, 2):
        grid = np.maximum.accumulate(grid, axis=axis)
    return _apply_boundaries_3d(grid, need_axis)


def linked_chase_table(base: ResourceTable, need_step: int = NEED_STEP, need_max: int = NEED_MAX) -> ChaseTable:
    """Chase table derived from the first-innings table for thin pools.

    Permitted fallback where a competition has too few chase deliveries to fit
    `need` directly. Every value produced this way is flagged so a consumer can
    see that the chase valuation was linked rather than fitted.
    """
    n_need = need_max // need_step + 1
    need_axis = np.arange(n_need, dtype=float) * need_step
    grid = np.minimum(base.grid[:, :, None], need_axis[None, None, :])
    counts = np.zeros(grid.shape, dtype=np.int64)
    table = ChaseTable(grid=grid, counts=counts, balls=base.balls, need_step=need_step)
    table.linked = True
    return table


def fit_environment(
    innings: pd.DataFrame,
    table: ResourceTable,
    *,
    venue_prior: int = VENUE_PRIOR_INNINGS,
) -> ResourceTable:
    """Competition, era, and venue offsets on the full-resource run scale.

    Venue residuals are estimated last and shrunk by their own sample size, so a
    ground with three matches does not get its own park factor.
    """
    full = float(table.grid[table.balls, MAX_WICKETS])
    if innings.empty or full <= 0:
        return table
    resid = innings["runs"].to_numpy(dtype=float) - full

    comp = {}
    df = innings.assign(resid=resid)
    for name, g in df.groupby("competition", sort=True):
        comp[name] = float(g["resid"].mean())
    df["resid1"] = df["resid"] - df["competition"].map(comp).fillna(0.0)

    era = {}
    for name, g in df.groupby("era", sort=True):
        era[name] = float(g["resid1"].mean())
    df["resid2"] = df["resid1"] - df["era"].map(era).fillna(0.0)

    venue = {}
    for name, g in df.groupby("venue", sort=True):
        n = len(g)
        lam = n / (n + venue_prior)
        venue[name] = float(lam * g["resid2"].mean())

    table.competition = comp
    table.era = era
    table.venue = venue
    return table


def era_label(start_date: pd.Series, span: int = ERA_YEARS) -> pd.Series:
    year = pd.to_numeric(start_date.astype(str).str.slice(0, 4), errors="coerce").fillna(0).astype(int)
    bucket = (year // span) * span
    return bucket.astype(str)


def logistic_fit(
    X: np.ndarray,
    y: np.ndarray,
    *,
    weights: np.ndarray | None = None,
    ridge: float = 1e-4,
    iters: int = 60,
) -> np.ndarray:
    """Newton-Raphson logistic regression with a light ridge for conditioning.

    `y` may be a proportion with `weights` giving the trial count, which is how
    a binomial observation such as wins-out-of-games is fitted without expanding
    it to one row per trial.
    """
    n, k = X.shape
    beta = np.zeros(k, dtype=float)
    penalty = ridge * np.eye(k)
    penalty[0, 0] = 0.0
    m = np.ones(n) if weights is None else np.asarray(weights, dtype=float)
    for _ in range(iters):
        z = np.clip(X @ beta, -30, 30)
        p = 1.0 / (1.0 + np.exp(-z))
        g = X.T @ (m * (y - p)) - ridge * beta
        wgt = m * np.maximum(p * (1 - p), 1e-8)
        H = X.T @ (X * wgt[:, None]) + penalty
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(H, g, rcond=None)[0]
        beta = beta + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return beta
