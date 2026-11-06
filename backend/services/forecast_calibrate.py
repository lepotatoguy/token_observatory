"""Tokens per percent of a weekly window, learned from past percent readings.

Two readings in the same weekly window, a few points apart, give a ratio: the
tokens logged between them divided by the percent that was spent.
"""
from bisect import bisect_right
from dataclasses import dataclass
from itertools import accumulate
from statistics import median

MIN_RISE = 2        # Percent is whole numbers, so smaller steps are mostly rounding.
OUTLIER = 4         # A ratio this many times above or below the median is dropped.
RESET_GAP = 3600    # Seconds between two reset times that mark different windows.


@dataclass(frozen=True)
class Calibration:
    value: float
    pairs: int


def segments(samples):
    """Readings in time order, split wherever the weekly window changed."""
    current = []
    for sample in sorted(samples, key=lambda item: item.t):
        if current:
            last = current[-1]
            moved = sample.resets_at is not None and last.resets_at is not None and abs(sample.resets_at - last.resets_at) > RESET_GAP
            if sample.percent < last.percent or moved:
                yield current
                current = []
        current.append(sample)
    if current:
        yield current


def pairs_in(segment):
    """(start, end) readings at least MIN_RISE apart; each pair starts where the last one ended."""
    start = 0
    for end in range(1, len(segment)):
        if segment[end].percent - segment[start].percent >= MIN_RISE:
            yield segment[start], segment[end]
            start = end


def tokens_per_percent(samples, events):
    """The pooled ratio over usable pairs, or None; `events` is sorted [(seconds, tokens)]."""
    times = [at for at, _ in events]
    running = [0, *accumulate(tokens for _, tokens in events)]
    found = []
    for segment in segments(samples):
        for first, last in pairs_in(segment):
            tokens = running[bisect_right(times, last.t)] - running[bisect_right(times, first.t)]
            if tokens > 0:
                found.append((tokens, last.percent - first.percent))
    if not found:
        return None
    typical = median(tokens / rise for tokens, rise in found)
    kept = [(tokens, rise) for tokens, rise in found if typical / OUTLIER <= tokens / rise <= typical * OUTLIER]
    return Calibration(sum(t for t, _ in kept) / sum(r for _, r in kept), len(kept))
