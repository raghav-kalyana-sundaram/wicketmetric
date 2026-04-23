"""Cross-fitted, hierarchically shrunk conditional expectations.

Every comparison baseline and every expected-rate model in the methodology is
the same object: the mean outcome among deliveries in a comparable situation,
estimated without the match being valued.

Two requirements shape the implementation.

Out of fold. A delivery must never be compared against a baseline its own match
helped fit, or good players quietly raise the bar they are measured against.
Folds are whole matches: deliveries inside a match are correlated, so splitting
them across folds leaks.

Partial pooling. The finest cell — competition, era, innings type, balls
remaining, wickets in hand, how set the batter is, free hit, target pressure —
is often thin. Rather than coarsen it for everyone, each level shrinks toward
its parent by sample size, so a well-populated cell speaks for itself and a
sparse one borrows from the situation above it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_PRIOR = 25.0


def encode(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    """Integer cell code for a set of key columns.

    Factorising a packed key is much cheaper than grouping on several object
    columns, and these groupings run for every model on every delivery.
    """
    codes = np.zeros(len(frame), dtype=np.int64)
    for col in columns:
        col_codes = pd.factorize(frame[col], use_na_sentinel=False)[0].astype(np.int64)
        codes = codes * (col_codes.max() + 2) + (col_codes + 1)
    return pd.factorize(codes, use_na_sentinel=False)[0].astype(np.int64)


class Hierarchy:
    """Reusable level codes for one covariate set."""

    def __init__(self, frame: pd.DataFrame, levels: list[list[str]], folds: np.ndarray, n_folds: int):
        self.levels = levels
        self.n_folds = n_folds
        self.folds = folds.astype(np.int64)
        self.codes = [encode(frame, cols) for cols in levels]
        self.sizes = [int(c.max()) + 1 if len(c) else 0 for c in self.codes]

    def out_of_fold_mean(
        self, y: np.ndarray, mask: np.ndarray, prior: float = DEFAULT_PRIOR
    ) -> np.ndarray:
        """Shrunk out-of-fold expectation of `y`, fitted on rows where `mask`.

        `mask` is the fitting universe — every eligible event of the relevant
        kind. It is deliberately not the leaderboard qualification rule: letting
        a display threshold decide what counts as average would make "average"
        mean "average among players good enough to qualify".
        """
        y = np.nan_to_num(np.asarray(y, dtype=float))
        fit = np.asarray(mask, dtype=bool)
        weights = fit.astype(float)
        wy = y * weights

        parent = np.full(len(y), float(np.sum(wy) / max(np.sum(weights), 1.0)))
        for codes, size in zip(self.codes, self.sizes):
            if size == 0:
                continue
            total_n = np.bincount(codes, weights=weights, minlength=size)
            total_s = np.bincount(codes, weights=wy, minlength=size)
            fold_key = codes * self.n_folds + self.folds
            fold_n = np.bincount(fold_key, weights=weights, minlength=size * self.n_folds)
            fold_s = np.bincount(fold_key, weights=wy, minlength=size * self.n_folds)

            own_n = fold_n[fold_key]
            own_s = fold_s[fold_key]
            oof_n = total_n[codes] - own_n
            oof_s = total_s[codes] - own_s
            parent = (oof_s + prior * parent) / (oof_n + prior)
        return parent

    def full_mean(self, y: np.ndarray, mask: np.ndarray, prior: float = DEFAULT_PRIOR) -> np.ndarray:
        """In-sample version, for diagnostics and calibration reports only."""
        y = np.nan_to_num(np.asarray(y, dtype=float))
        weights = np.asarray(mask, dtype=bool).astype(float)
        wy = y * weights
        parent = np.full(len(y), float(np.sum(wy) / max(np.sum(weights), 1.0)))
        for codes, size in zip(self.codes, self.sizes):
            if size == 0:
                continue
            n = np.bincount(codes, weights=weights, minlength=size)
            s = np.bincount(codes, weights=wy, minlength=size)
            parent = (s[codes] + prior * parent) / (n[codes] + prior)
        return parent


def match_folds(match_ids: pd.Series, n_folds: int = 5, seed: int = 20260829) -> np.ndarray:
    """Assign whole matches to folds, deterministically.

    A stable hash means a rebuild reproduces the same split without storing it,
    and the seed is published with the model configuration.
    """
    codes = pd.factorize(match_ids, use_na_sentinel=False)[0].astype(np.int64)
    rng = np.random.default_rng(seed)
    lookup = rng.integers(0, n_folds, size=int(codes.max()) + 1 if len(codes) else 1)
    return lookup[codes]


def bucket(values: pd.Series, edges: tuple[int, ...]) -> np.ndarray:
    """Right-open bucket index, for opportunity counts and similar."""
    v = np.nan_to_num(values.to_numpy(dtype=float))
    return np.searchsorted(np.asarray(edges, dtype=float), v, side="right").astype(np.int16)
