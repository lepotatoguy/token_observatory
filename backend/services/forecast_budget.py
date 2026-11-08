"""Today's suggested budget from the weekly limit that is left and the fitted demand weights.

A pure function of the stored model state, the live snapshot and the clock, so it
can run on every request while the model itself is fitted once a day.
"""
import datetime as dt

from backend.services import forecast_demand, quota

PROVIDERS = ('claude', 'codex', 'minimax')
MIN_PAIRS = 2   # Fewer calibration pairs, or fewer history days than forecast_demand.LOW_DAYS, count as too little data.
MAX_DAYS = 15  # A weekly window spans at most 8 calendar days; the cap only guards bad reset times.


def midnight(day):
    return dt.datetime.combine(day, dt.time()).timestamp()


def weekly(limits):
    """The weekly window, its reset-estimated flag and its window start, or None."""
    if not isinstance(limits, dict):
        return None
    window = quota.pick(limits, quota.WEEKLY_MINUTES, 'secondary')
    if not window or window['used_percent'] is None or window['resets_at'] is None:
        return None
    raw = next((limits[slot] for slot in quota.SLOTS if isinstance(limits.get(slot), dict) and quota.number(limits[slot].get('window_minutes')) == quota.WEEKLY_MINUTES),
               limits.get('secondary'))
    return dict(window, estimated=bool(raw.get('resets_estimated')))


def tokens_since(snapshot, provider, start, end):
    total = 0
    for session in snapshot.get('sessions') or []:
        if session.get('provider') == provider:
            for event in session.get('events') or []:
                at = event.get('at')
                if isinstance(at, (int, float)) and start <= at <= end:
                    total += sum(quota.number(event.get(k)) or 0 for k in ('input', 'cached', 'write', 'output'))
    return total


def day_weights(weights, first_day, start, resets_at):
    """Demand weight of each local day from `first_day` to the reset, scaled by the part of the day inside the window."""
    result = []
    for offset in range(MAX_DAYS):
        day = first_day + dt.timedelta(days=offset)
        begin, end = midnight(day), midnight(day + dt.timedelta(days=1))
        if begin >= resets_at:
            break
        inside = max(0.0, min(end, resets_at) - max(begin, start))
        result.append(weights[day.weekday()] * inside / (end - begin))
    return result


def entry(state, snapshot, provider, now):
    saved = (state.get('providers') or {}).get(provider) or {}
    demand = saved.get('demand') or {}
    info = dict(demand_method=demand.get('method', 'flat'), confidence=saved.get('confidence', 'low'),
                days_used=saved.get('days_used', 0), calibration=None, calibration_pairs=saved.get('calibration_pairs', 0),
                shrinkage=demand.get('shrinkage', 0.0), backtest=demand.get('backtest'),
                calibration_kind=(saved.get('calibration_model') or {}).get('kind'),
                calibration_readings=(saved.get('calibration_model') or {}).get('readings', saved.get('calibration_pairs', 0)),
                rolling=saved.get('rolling'), budget_check=saved.get('budget_check'), estimated=False, daily=None, share=None,
                start_of_day_capacity=None, remaining_capacity=None, used_today=None, excluded=None,
                warnings=list(saved.get('warnings') or []))
    limits = (snapshot.get('limits') or {}).get(provider)
    week = weekly(limits)
    if not week or week['resets_at'] <= now:
        return dict(info, excluded='no_weekly_quota')
    info['estimated'] = week['estimated']
    window_start = week['resets_at'] - week['window_minutes'] * 60
    today = dt.datetime.fromtimestamp(now).date()
    start = max(window_start, midnight(today))
    percent = week['used_percent']
    k = saved.get('tokens_per_percent')
    enough = (isinstance(k, (int, float)) and k > 0 and info['calibration_pairs'] >= MIN_PAIRS
              and info['days_used'] >= forecast_demand.LOW_DAYS)
    if not enough:
        return dict(info, excluded='insufficient_data')
    info['calibration'] = 'history'
    used_today = tokens_since(snapshot, provider, start, now)
    remaining = k * max(0.0, 100 - percent)
    capacity = remaining + used_today
    weights = day_weights(demand.get('weekday_weights') or (1.0,) * 7, today, start, week['resets_at'])
    share = weights[0] / sum(weights)
    return dict(info, daily=round(capacity * share), share=share, start_of_day_capacity=capacity,
                remaining_capacity=remaining, used_today=used_today)


def budget(state, snapshot, now):
    """The per-provider budgets for the enabled providers and their total."""
    enabled = (snapshot.get('providers') or {}).get('enabled') or []
    providers = {p: entry(state, snapshot, p, now) for p in PROVIDERS if p in enabled}
    return dict(date=dt.datetime.fromtimestamp(now).date().isoformat(), generated_at=state.get('generated_at'),
                total=sum(p['daily'] or 0 for p in providers.values()), warnings=list(state.get('warnings') or []),
                providers=providers)
