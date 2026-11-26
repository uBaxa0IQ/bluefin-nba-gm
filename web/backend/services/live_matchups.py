"""One ESPN fantasy snapshot for credited totals, locked slots and live games."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import math
from time import monotonic

import requests
from espn_api.basketball.constant import STATS_MAP
from espn_api.requests.espn_requests import ESPNAccessDenied, ESPNInvalidLeague, ESPNUnknownError

from core.live_games import (
    DOUBLE_DOUBLE_STATS, LIVE_CACHE_SECONDS, LIVE_COMPONENTS, LIVE_WINDOW_SECONDS, LiveGame,
    expected_remainder, remaining_fraction, started_games,
)
from core.matchup_value import combine_stats
from core.projection import build_matchup_lineups, project_team_stats
from core.roster_rules import SLOT_NAMES


logger = logging.getLogger(__name__)


def _stats(values):
    return {STATS_MAP.get(key, key): float(value) for key, value in values.items()
            if isinstance(value, (int, float)) and math.isfinite(value)}


def _split_stats(entry, split_id, day):
    player = entry['playerPoolEntry']['player']
    for row in player.get('stats', ()):
        if row.get('id') == split_id and row.get('scoringPeriodId') == day:
            return _stats(row.get('stats') or {})
    return {}


def _weekly_players(side, key):
    return {entry['playerId']: _split_stats(entry, '05null', 0)
            for entry in side.get(key, {}).get('entries', ())}


def _score(side, key):
    return _stats({code: row.get('score') for code, row in side.get(key, {}).get('scoreByStat', {}).items()})


def _nba_summary(game_id):
    url = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary'
    try:
        response = requests.get(url, params={'event': game_id}, timeout=(3, 5))
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}
    except (requests.RequestException, ValueError):
        return {}


def read_fantasy_day(league, week, day):
    filters = {'schedule': {'filterMatchupPeriodIds': {'value': [week]}}}
    return league.espn_request.league_get(
        params={'view': ['mMatchupScore', 'mScoreboard'], 'scoringPeriodId': day},
        headers={'x-fantasy-filter': json.dumps(filters)},
    )


def read_live_matchup_totals(league, week, team_id, opponent_id):
    if week != int(league.currentMatchupPeriod):
        return {}
    try:
        data = read_fantasy_day(league, week, int(league.scoringPeriodId))
        for matchup in data.get('schedule', ()):
            if matchup.get('matchupPeriodId') != week or matchup.get('winner') in ('HOME', 'AWAY', 'TIE'):
                continue
            sides = [matchup.get(key) or {} for key in ('home', 'away')]
            if {side.get('teamId') for side in sides} == {team_id, opponent_id}:
                return {side['teamId']: _score(side, 'cumulativeScoreLive') for side in sides}
    except (AttributeError, KeyError, TypeError, ValueError, requests.RequestException,
            ESPNAccessDenied, ESPNInvalidLeague, ESPNUnknownError) as error:
        logger.warning('ESPN live scoreboard unavailable (%s)', type(error).__name__)
    return {}


def _live_box(data):
    competitions = data.get('header', {}).get('competitions', ())
    status = competitions[0].get('status', {}) if competitions else {}
    if status.get('type', {}).get('state') != 'in':
        return 0, 0.0, {}
    try:
        period = int(status['period'])
        whole_minutes, _, seconds = str(status['displayClock']).rpartition(':')
        minutes = int(whole_minutes or 0) + float(seconds) / 60
        if period < 1 or not 0 <= minutes <= (12 if period <= 4 else 5):
            return 0, 0.0, {}
        minutes += 12 * max(0, 4 - period)
    except (KeyError, ValueError, TypeError):
        return 0, 0.0, {}

    return period, minutes, nba_player_lines(data)


def nba_player_lines(data):
    players = {}
    for team in data.get('boxscore', {}).get('players', ()):
        for group in team.get('statistics', ()):
            for row in group.get('athletes', ()):
                if row.get('didNotPlay') or row.get('ejected'):
                    continue
                raw = dict(zip(group.get('labels', ()), row.get('stats', ())))
                try:
                    stats = {key: int(raw[key]) for key in ('MIN', *DOUBLE_DOUBLE_STATS, 'TO')}
                    for label, made, attempts in (('FG', 'FGM', 'FGA'), ('3PT', '3PM', '3PA'), ('FT', 'FTM', 'FTA')):
                        stats[made], stats[attempts] = map(int, raw[label].split('-'))
                    stats['DD'] = int(sum(stats[k] >= 10 for k in DOUBLE_DOUBLE_STATS) >= 2)
                    players[int(row['athlete']['id'])] = stats
                except (KeyError, ValueError, TypeError):
                    continue
    return players


@dataclass(frozen=True)
class CurrentMatchup:
    as_of: datetime
    day: int
    actual: dict
    locked_slots: dict
    confirmed: dict
    opponents: dict

    def open_slots(self, team_id, slots):
        available = list(slots)
        for slot in self.locked_slots.get(team_id, ()):
            if slot in available:
                available.remove(slot)
        return tuple(available)

    def remainders(self, team_id, players):
        result = {}
        for pid, (period, clock, actual) in self.confirmed.get(team_id, {}).items():
            stats = players.get(pid, {}).get('stats') or {}
            fraction = remaining_fraction(stats.get('MIN') or stats.get('MPG') or 0, actual['MIN'], clock, period)
            if fraction:
                result[pid] = LiveGame(fraction, actual)
        return result


def _parse_matchup(raw, week, day, as_of, started, boxes, slots):
    actual, locked, confirmed, opponents = {}, {}, {}, {}
    for matchup in raw.get('schedule', ()):
        if matchup.get('matchupPeriodId') != week:
            continue
        for key, other in (('home', 'away'), ('away', 'home')):
            side = matchup.get(key)
            if not side:
                continue
            team_id = side['teamId']
            if matchup.get(other):
                opponents[team_id] = matchup[other]['teamId']
            settled = _score(side, 'cumulativeScore')
            live = _score(side, 'cumulativeScoreLive')
            actual[team_id] = live or settled
            locked[team_id], confirmed[team_id] = [], {}
            credited = _weekly_players(side, 'rosterForMatchupPeriod')
            delayed = _weekly_players(side, 'rosterForMatchupPeriodDelayed')
            # Match the live team scoreboard to its credited weekly player totals.
            verified = bool(live) and all(
                live[k] == sum(stats.get(k, 0) for stats in credited.values()) for k in LIVE_COMPONENTS if k in live)
            for entry in side.get('rosterForCurrentScoringPeriod', {}).get('entries', ()):
                player = entry['playerPoolEntry']['player']
                slot = SLOT_NAMES.get(entry['lineupSlotId'])
                games = started.get(player['proTeamId'], ())
                if slot not in slots or not games:
                    continue
                locked[team_id].append(slot)
                if not verified or len(games) != 1:
                    continue
                game_id = games[0]['id']
                period, clock, public_rows = boxes.get(game_id, (0, 0., {}))
                pid = player['id']
                public = public_rows.get(pid)
                today = _split_stats(entry, f'05{game_id}', day)
                before = delayed.get(pid, {})
                included = credited.get(pid, {})
                keys = (*LIVE_COMPONENTS, 'MIN')
                if (public and clock and today.get('MIN', 0) > 0 and
                        all(public.get(k, 0) == today.get(k, 0) ==
                            included.get(k, 0) - before.get(k, 0) for k in keys)):
                    confirmed[team_id][pid] = (period, clock, today)
    return CurrentMatchup(as_of, day, actual, locked, confirmed, opponents)


def current_matchup(metadata, week, slots):
    league = metadata.league
    as_of = datetime.now(timezone.utc)
    day = int(getattr(league, 'scoringPeriodId', None) or getattr(league, 'current_week', 0))
    started = started_games(league, as_of)
    unavailable = CurrentMatchup(as_of, day, {}, {}, {}, {})
    if week != int(league.currentMatchupPeriod) or not any(started.values()):
        return unavailable
    game_ids = {g['id'] for games in started.values() for g in games if not g.get('statsOfficial')
                and as_of.timestamp() - g['date'] / 1000 < LIVE_WINDOW_SECONDS}
    key = (id(league), week, day, tuple(sorted(game_ids)), tuple(slots))
    cached = getattr(metadata, '_live_matchup_cache', None)
    if cached and cached[0] == key and monotonic() - cached[1] < LIVE_CACHE_SECONDS:
        # Keep the projection cutoff current even when credits are shared.
        return CurrentMatchup(as_of, day, cached[2].actual, cached[2].locked_slots, cached[2].confirmed, cached[2].opponents)
    try:
        with ThreadPoolExecutor(max_workers=min(8, 1 + len(game_ids))) as pool:
            summaries = {gid: pool.submit(_nba_summary, gid) for gid in game_ids}
            raw = read_fantasy_day(league, week, day)
            boxes = {gid: _live_box(task.result()) for gid, task in summaries.items()}
        result = _parse_matchup(raw, week, day, as_of, started, boxes, slots)
    except (AttributeError, KeyError, TypeError, ValueError, requests.RequestException,
            ESPNAccessDenied, ESPNInvalidLeague, ESPNUnknownError) as error:
        logger.warning('ESPN live matchup data unavailable (%s)', type(error).__name__)
        if cached and cached[0] == key:
            last = cached[2]
            return CurrentMatchup(as_of, day, last.actual, last.locked_slots, {}, last.opponents)
        return unavailable
    metadata._live_matchup_cache = (key, monotonic(), result)
    return result


def current_totals(metadata, week, team_id, current):
    if current and team_id in current.actual:
        return current.actual[team_id]
    box = metadata.get_matchup_box_score(week, team_id)
    return box['totals'] if box else {}


def current_opponent(metadata, week, team_id, current):
    if team_id in current.opponents:
        return current.opponents[team_id]
    box = metadata.get_matchup_box_score(week, team_id)
    return box['opponent_id'] if box else None


def future_lineups(players, days, slots, punts, *, current=None, team_id=None, fill_slots=True):
    daily_slots = {current.day: current.open_slots(team_id, slots)} if current else {}
    if current:
        players = [{**p, 'as_of': current.as_of} for p in players]
    return build_matchup_lineups(players, days, slots, punts, fill_slots, daily_slots=daily_slots)


def future_stats(players, lineup, live_players, remainders):
    total = project_team_stats(players, lineup['selected_games'])
    if not remainders:
        return total
    return combine_stats(total, remainder_stats(live_players, remainders))


def remainder_stats(players, remainders):
    return combine_stats(*(expected_remainder(players[pid]['stats'], game) for pid, game in remainders.items()))
