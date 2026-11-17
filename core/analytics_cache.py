"""Stable content keys for analytics; never include credentials or fetch timestamps."""
from bisect import bisect_right
from datetime import date, datetime
import hashlib
import json
import time

from .weighted_coefficients import load_weighted_coefficients

CACHE_REVISION = 'analytics-v2'


def canonical(value):
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(canonical(v) for v in value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def digest(value):
    return hashlib.sha256(json.dumps(canonical(value), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def capture_league_inputs(metadata, raw):
    players, dates = [], set()
    for team in sorted(metadata.teams, key=lambda t: t.team_id):
        roster = []
        for player in sorted(team.roster, key=lambda p: p.playerId):
            fields = {k: getattr(player, k, None) for k in (
                'playerId', 'name', 'stats', 'schedule', 'position', 'eligibleSlots',
                'lineupSlot', 'proTeam', 'injured', 'injuryStatus', 'expected_return_date')}
            roster.append(fields)
            for game in (fields['schedule'] or {}).values():
                when = game.get('date')
                if isinstance(when, datetime):
                    dates.add(when.timestamp())
        players.append({'team_id': team.team_id, 'name': team.team_name,
            'record': [getattr(team, k, 0) for k in ('wins', 'losses', 'ties')], 'roster': roster})
    metadata.analytics_data_version = digest({
        'league': metadata.league_id, 'year': metadata.year, 'players': players,
        'settings': raw.get('settings', {}), 'schedule': raw.get('schedule', []),
        'periods': [getattr(metadata.league, k, None) for k in ('currentMatchupPeriod', 'current_week', 'scoringPeriodId')],
    })
    metadata.analytics_game_dates = tuple(sorted(dates))


def analytics_version(metadata, *, stochastic=False):
    version = getattr(metadata, 'analytics_data_version', None)
    if version is None:
        # Adapters without a captured ESPN snapshot retain conservative invalidation.
        version = str(getattr(metadata, 'last_refresh_time', ''))
    return digest([CACHE_REVISION, metadata.league_id, metadata.year, version,
        load_weighted_coefficients(), bisect_right(getattr(metadata, 'analytics_game_dates', ()), time.time()),
        # Game-log reads have a six-hour freshness limit, independent of league refresh.
        int(time.time() // (6 * 3600)) if stochastic else None])
