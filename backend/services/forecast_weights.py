"""Per token type calibration: how many percent of the weekly limit each kind of token costs.

Pairs of percent readings give a rise in percent and the tokens logged between them, split
by type. A non-negative least-squares fit over the pairs gives one weight per type. With
four types the exact optimum is found by trying every subset of types, so no iterative
solver is needed and the result is deterministic.
"""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import datetime as dt
from itertools import accumulate
from statistics import median

from backend.services import forecast_calibrate

TYPES = ('input', 'cached', 'write', 'output')
MIN_TYPED_PAIRS = 20   # Fewer pairs cannot support four weights.
MARGIN = 0.9           # The by-type fit must have at most 90% of the single ratio's held-out error.
RIDGE = 1e-9           # Relative; only keeps nearly collinear columns solvable.


@dataclass(frozen=True)
class Pair:
    t_end: float
    rise: float
    tokens: tuple   # Millions of tokens: input, cached, write, output.


@dataclass(frozen=True)
class Loo:
    single: float
    by_type: float | None


@dataclass(frozen=True)
class Calibration:
    kind: str
    weights: tuple | None
    pairs: int
    loo_single: float | None
    loo_by_type: float | None


class Index:
    """Token sums by type over any time range, from sorted rows (seconds, input, cached, write, output)."""

    def __init__(self, typed):
        columns = list(zip(*typed)) if typed else [(), (), (), (), ()]
        self.times = list(columns[0])
        self.running = [list(accumulate(columns[i + 1], initial=0)) for i in range(4)]

    def between(self, low, high, closed='right'):
        """Tokens by type for events in (low, high] or, with closed='left', in [low, high)."""
        find = bisect_right if closed == 'right' else bisect_left
        a, b = find(self.times, low), find(self.times, high)
        return tuple(run[b] - run[a] for run in self.running)


def typed_pairs(samples, typed, index=None):
    """Usable reading pairs with typed tokens; `typed` is sorted [(seconds, input, cached, write, output)]."""
    index = index or Index(typed)
    found = []
    for segment in forecast_calibrate.segments(samples):
        for first, last in forecast_calibrate.pairs_in(segment):
            tokens = tuple(value / 1e6 for value in index.between(first.t, last.t))
            if sum(tokens) > 0:
                found.append(Pair(last.t, last.percent - first.percent, tokens))
    if not found:
        return []
    typical = median(p.rise / sum(p.tokens) for p in found)
    kept = [p for p in found if typical / forecast_calibrate.OUTLIER <= p.rise / sum(p.tokens) <= typical * forecast_calibrate.OUTLIER]
    return sorted(kept, key=lambda pair: pair.t_end)


def solve(matrix, vector):
    """Gaussian elimination with partial pivoting, or None when the system is singular."""
    n = len(vector)
    rows = [list(matrix[i]) + [vector[i]] for i in range(n)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda r: abs(rows[r][column]))
        if abs(rows[pivot][column]) < 1e-12:
            return None
        rows[column], rows[pivot] = rows[pivot], rows[column]
        for r in range(column + 1, n):
            factor = rows[r][column] / rows[column][column]
            for c in range(column, n + 1):
                rows[r][c] -= factor * rows[column][c]
    result = [0.0] * n
    for r in range(n - 1, -1, -1):
        result[r] = (rows[r][n] - sum(rows[r][c] * result[c] for c in range(r + 1, n))) / rows[r][r]
    return result


def fit_nnls(pairs):
    """Non-negative weights (percent per million tokens) minimising squared error, or None without pairs."""
    if not pairs:
        return None
    gram = [[sum(p.tokens[i] * p.tokens[j] for p in pairs) for j in range(4)] for i in range(4)]
    moment = [sum(p.tokens[i] * p.rise for p in pairs) for i in range(4)]
    scale = max(gram[i][i] for i in range(4)) or 1.0
    best, best_error = (0.0,) * 4, sum(p.rise ** 2 for p in pairs)
    for mask in range(1, 16):
        columns = [i for i in range(4) if mask >> i & 1]
        small = [[gram[i][j] + (RIDGE * scale if i == j else 0.0) for j in columns] for i in columns]
        solved = solve(small, [moment[i] for i in columns])
        if solved is None or min(solved) < 0:
            continue
        weights = [0.0] * 4
        for i, value in zip(columns, solved):
            weights[i] = value
        error = sum((p.rise - sum(w * t for w, t in zip(weights, p.tokens))) ** 2 for p in pairs)
        if error < best_error - 1e-12:
            best, best_error = tuple(weights), error
    return best


def single_percent_per_million(pairs):
    tokens = sum(sum(p.tokens) for p in pairs)
    return sum(p.rise for p in pairs) / tokens if tokens else None


def single_tokens_per_percent(pairs):
    ratio = single_percent_per_million(pairs)
    return 1e6 / ratio if ratio else None


def predict(weights, pair):
    return sum(w * t for w, t in zip(weights, pair.tokens))


def loo_errors(pairs):
    """Leave-one-out mean absolute error in percentage points; by-type only with enough pairs."""
    if len(pairs) < 2:
        return None
    single, typed = [], []
    for i, pair in enumerate(pairs):
        others = pairs[:i] + pairs[i + 1:]
        ratio = single_percent_per_million(others)
        single.append(abs(sum(pair.tokens) * ratio - pair.rise) if ratio is not None else pair.rise)
        if len(pairs) >= MIN_TYPED_PAIRS:
            weights = fit_nnls(others)
            typed.append(abs(predict(weights, pair) - pair.rise))
    return Loo(sum(single) / len(single), sum(typed) / len(typed) if typed else None)


def choose(pairs):
    """The by-type fit when it is supported and clearly better on held-out pairs, else the single ratio."""
    if not pairs:
        return None
    errors = loo_errors(pairs)
    loo_single = errors.single if errors else None
    loo_typed = errors.by_type if errors else None
    if loo_typed is not None and loo_typed <= MARGIN * loo_single:
        weights = fit_nnls(pairs)
        if weights and any(weights):
            return Calibration('by_type', weights, len(pairs), loo_single, loo_typed)
    return Calibration('single', None, len(pairs), loo_single, loo_typed)


def shares(totals):
    total = sum(totals)
    return tuple(value / total for value in totals) if total > 0 else None


def pairs_mix(pairs):
    """Each type's share of the tokens inside the reading pairs, or None."""
    return shares([sum(p.tokens[i] for p in pairs) for i in range(4)])


def recent_mix(index, today, days=7):
    """Each type's share of the tokens over the `days` local days before `today`, or None."""
    end = dt.datetime.combine(today, dt.time()).timestamp()
    start = dt.datetime.combine(today - dt.timedelta(days=days), dt.time()).timestamp()
    return shares(index.between(start, end, 'left'))


def effective_tokens_per_percent(weights, mix):
    """Tokens per percent for a token mix: one over the weighted cost per token."""
    cost = sum(w * m for w, m in zip(weights, mix))  # Percent per million tokens.
    return 1e6 / cost if cost > 0 else None
