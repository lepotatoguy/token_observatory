"""Relative demand for each weekday, learned from a provider's daily token totals.

Only the relative size of the weights matters to the budget, so the model is a
weekday multiplier shrunk toward 1. A backtest on the user's own days chooses the
shrinkage; when no shrinkage beats the flat baseline, every weekday weighs the same.
"""
from dataclasses import dataclass
import datetime as dt

BASELINE_DAYS = 14        # The flat baseline predicts a day as the mean of the previous 14 days.
MIN_DAYS = 18             # Fewer days leave too little to test a weekday pattern.
SHRINKAGE = (0.0, 0.25, 0.5, 0.75, 1.0)
FLOOR = 0.05              # Keeps every weight positive.
LOW_DAYS, MEDIUM_DAYS = 7, 18


@dataclass(frozen=True)
class Backtest:
    model_mae: float
    baseline_mae: float
    days: int


@dataclass(frozen=True)
class Demand:
    method: str
    weekday_weights: tuple
    shrinkage: float
    backtest: Backtest | None
    days_used: int
    confidence: str


def mean(values):
    return sum(values) / len(values) if values else 0.0


def ratios(train, weekdays):
    """Mean use on each weekday divided by the overall mean; 1 where there is nothing to compare."""
    overall = mean(train)
    result = []
    for weekday in range(7):
        found = [value for value, day in zip(train, weekdays) if day == weekday]
        result.append(mean(found) / overall if found and overall > 0 else 1.0)
    return result


def weights(ratio, shrinkage):
    return tuple(max(FLOOR, (1 - shrinkage) + shrinkage * r) for r in ratio)


def backtest_errors(series, weekdays):
    """Mean absolute error in tokens for each shrinkage, predicting each day from earlier days only."""
    errors = {shrinkage: 0.0 for shrinkage in SHRINKAGE}
    tested = range(BASELINE_DAYS, len(series))
    for t in tested:
        level = mean(series[max(0, t - BASELINE_DAYS):t])
        ratio = ratios(series[:t], weekdays[:t])
        for shrinkage in SHRINKAGE:
            errors[shrinkage] += abs(series[t] - level * weights(ratio, shrinkage)[weekdays[t]])
    return {shrinkage: total / len(tested) for shrinkage, total in errors.items()}, len(tested)


def confidence(days):
    return 'low' if days < LOW_DAYS else 'medium' if days < MEDIUM_DAYS else 'normal'


def fit_demand(series, last_day):
    """Demand weights for one provider; `series` is oldest first and ends on `last_day`."""
    days = len(series)
    flat = Demand('flat', (1.0,) * 7, 0.0, None, days, confidence(days))
    if days < MIN_DAYS:
        return flat
    weekdays = [(last_day - dt.timedelta(days=days - 1 - i)).weekday() for i in range(days)]
    errors, tested = backtest_errors(series, weekdays)
    best = min(SHRINKAGE, key=lambda shrinkage: (errors[shrinkage], shrinkage))
    result = Backtest(errors[best], errors[0.0], tested)
    if best == 0.0:
        return Demand('flat', flat.weekday_weights, 0.0, result, days, flat.confidence)
    return Demand('weekday_regression', weights(ratios(series, weekdays), best), best, result, days, flat.confidence)
