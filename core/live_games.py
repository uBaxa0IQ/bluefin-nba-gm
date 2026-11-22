"""Forecast only the unplayed part of a credited NBA game."""
from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp

from .projection import COMPONENT_STATS, COUNTING_STATS


DOUBLE_DOUBLE_STATS = ('PTS', 'REB', 'AST', 'STL', 'BLK')
LIVE_COMPONENTS = (*COUNTING_STATS, *COMPONENT_STATS)
LIVE_CACHE_SECONDS = 60
LIVE_WINDOW_SECONDS = 8 * 3600


def started_games(league, as_of):
    day = str(getattr(league, 'scoringPeriodId', None) or getattr(league, 'current_week', 0))
    return {
        team: [g for g in games.get(day, ()) if g.get('validForLocking', True)
               and 0 < g.get('date', 0) <= as_of.timestamp() * 1000]
        for team, games in (getattr(league, 'pro_schedule', None) or {}).items()
    }


def live_cache_tick(league, now, interval):
    games = started_games(league, datetime.fromtimestamp(now, timezone.utc))
    if any(not game.get('statsOfficial') and 0 <= now - game['date'] / 1000 < LIVE_WINDOW_SECONDS
           for schedule in games.values() for game in schedule):
        return int(now // interval)
    return None


@dataclass(frozen=True)
class LiveGame:
    fraction: float
    actual: dict[str, float]


def remaining_fraction(typical_minutes, played_minutes, clock_minutes, period):
    if (not isinstance(typical_minutes, (int, float)) or not 0 < typical_minutes <= 60
            or played_minutes <= 0 or clock_minutes <= 0):
        return 0.0
    budget = typical_minutes - played_minutes if period <= 4 else clock_minutes * min(1, typical_minutes / 48)
    return max(0.0, min(budget, clock_minutes) / typical_minutes)


def expected_remainder(stats, game):
    projected = {key: float(stats.get(key, 0)) * game.fraction for key in LIVE_COMPONENTS}
    # Estimate a new double-double from the existing game line and remaining
    # production. An already-earned double-double is in the credited totals.
    none, exactly_one = 1.0, 0.0
    projected['DD'] = 0.0
    if sum(game.actual.get(k, 0) >= 10 for k in DOUBLE_DOUBLE_STATS) >= 2:
        return projected
    for key in DOUBLE_DOUBLE_STATS:
        needed = max(0, 10 - int(game.actual.get(key, 0)))
        mean = projected[key]
        term = exp(-mean)
        below = 0.0
        for count in range(needed):
            below += term
            term *= mean / (count + 1)
        exactly_one = exactly_one * below + none * (1 - below)
        none *= below
    projected['DD'] = min(1.0, max(0.0, 1 - none - exactly_one))
    return projected
