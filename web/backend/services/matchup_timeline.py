"""Reconstruct a fantasy matchup at successive NBA final whistles."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
from espn_api.basketball.constant import STATS_MAP
from espn_api.requests.espn_requests import ESPNUnknownError
from requests import RequestException

from core.monte_carlo import COMPONENTS, RATIOS, category_arrays, compare_category_trials
from core.matchup_value import combine_stats
from core.projection import get_matchup_scoring_periods, optimize_daily_lineup
from core.roster_rules import SLOT_NAMES, league_slots
from core.z_score import calculate_z_scores_from_players
from .game_history import build_distributions
from .live_matchups import _nba_summary, _stats, nba_player_lines, read_fantasy_day


TRIALS = 4000
HISTORY = Path(__file__).resolve().parents[3] / '.cache' / 'monte_carlo' / 'game_logs'


class TimelineUnavailable(Exception):
    pass


@dataclass(frozen=True)
class NbaGame:
    id: int
    day: int
    tipoff: datetime


@dataclass(frozen=True)
class FinalGame:
    at: datetime
    name: str
    stats: dict


@lru_cache(maxsize=76)
def _daily_box(league, week, day, cache_bucket):
    for attempt in range(3):
        try:
            return read_fantasy_day(league, week, day)['schedule']
        except (RequestException, ESPNUnknownError, KeyError) as error:
            if attempt == 2:
                raise TimelineUnavailable('ESPN daily matchup unavailable') from error


@lru_cache(maxsize=512)
def _finished_game(event_id, cache_bucket):
    summary = _nba_summary(event_id)
    if not summary:
        summary = _nba_summary(event_id)
    competitions = summary.get('header', {}).get('competitions', ())
    if not competitions:
        raise TimelineUnavailable('NBA game status unavailable')
    status = competitions[0].get('status', {}).get('type', {})
    if not status.get('completed'):
        return None
    plays = summary.get('plays', ())
    last_period = max((play.get('period', {}).get('number', 0) for play in plays), default=0)
    ending = next((play['wallclock'] for play in reversed(plays) if play.get('wallclock')
                   and (play.get('type', {}).get('text') == 'End Game'
                        or play.get('type', {}).get('text') == 'End Period'
                        and play.get('period', {}).get('number') == last_period)), None)
    if not ending:
        raise TimelineUnavailable('NBA final timestamp unavailable')
    competitors = {row['homeAway']: row['team']['abbreviation'] for row in competitions[0].get('competitors', ())}
    return FinalGame(datetime.fromisoformat(ending.replace('Z', '+00:00')),
                     f"{competitors.get('away', '')} @ {competitors.get('home', '')}", nba_player_lines(summary))


def _find_match(metadata, week, team_id):
    for match in (getattr(metadata, 'league_data', None) or {}).get('schedule', ()):
        home, away = match.get('home') or {}, match.get('away') or {}
        if match.get('matchupPeriodId') == week and home.get('teamId') and away.get('teamId'):
            ids = home['teamId'], away['teamId']
            if team_id in ids:
                index = ids.index(team_id)
                outcome = ({'HOME': 1, 'AWAY': -1, 'TIE': 0}.get(match.get('winner')))
                return ids[1 - index], outcome if index == 0 or outcome is None else -outcome
    return None, None


def _nba_schedule(league, days):
    by_id, by_team_day = {}, defaultdict(list)
    for pro_team, schedule in (getattr(league, 'pro_schedule', None) or {}).items():
        for day in days:
            for item in schedule.get(str(day), ()):
                if not item.get('validForLocking', True) or not item.get('date'):
                    continue
                game = NbaGame(int(item['id']), day, datetime.fromtimestamp(item['date'] / 1000, timezone.utc))
                by_id[game.id] = game
                by_team_day[pro_team, day].append(game.id)
    return by_id, by_team_day


def _day_rosters(boxes, week, day, teams):
    for match in boxes:
        sides = {side['teamId']: side for key in ('home', 'away') if (side := match.get(key))}
        if match.get('matchupPeriodId') != week or not set(teams).issubset(sides):
            continue
        rosters = {}
        for tid in teams:
            archived = sides[tid].get('rosterForCurrentScoringPeriod', {})
            if 'entries' not in archived:
                raise TimelineUnavailable('ESPN daily lineup unavailable')
            roster = []
            for row in archived['entries']:
                player = row['playerPoolEntry']['player']
                splits = {}
                for split in player.get('stats', ()):
                    key = str(split.get('id', ''))
                    if split.get('scoringPeriodId') == day and key.startswith('05') and key[2:].isdigit():
                        values = _stats(split.get('stats', {}))
                        if values.get('GP') or values.get('MIN', 0) > 0:
                            splits[int(key[2:])] = values
                roster.append({
                    'player_id': player['id'], 'name': player['fullName'],
                    'pro_team': player['proTeamId'], 'slot': SLOT_NAMES.get(row['lineupSlotId']),
                    'eligible_slots': tuple(SLOT_NAMES.get(slot) for slot in player.get('eligibleSlots', ())),
                    'splits': splits,
                })
            rosters[tid] = roster
        return rosters
    raise TimelineUnavailable('ESPN daily matchup unavailable')


def _model_values(players, distributions, categories, reverse):
    rows = [{**player, 'team_id': 0, 'team_name': '', 'position': '',
             'stats': combine_stats(dict(zip(COMPONENTS, np.average(
                 distributions[pid].samples, axis=0, weights=distributions[pid].weights).tolist())))}
            for pid, player in players.items() if pid in distributions]
    scored = calculate_z_scores_from_players(rows, categories, reverse)['players']
    return {player['player_id']: sum(row['z_scores'].values())
            for player, row in zip(rows, scored, strict=True)}


def _planned_games(day, roster, days, slots, by_team_day, distributions, values):
    planned = set()
    for player in roster:
        pid = player['player_id']
        if player['slot'] in slots and pid in distributions:
            games = player['splits'] or by_team_day.get((player['pro_team'], day), ())
            planned.update((game, pid) for game in games)
    for future in days:
        if future <= day:
            continue
        candidates = [{**p, 'lineup_value': values.get(p['player_id'], 0)}
                      for p in roster if p['slot'] not in ('IR', 'Rookie') and p['player_id'] in distributions
                      and by_team_day.get((p['pro_team'], future))]
        for starter in optimize_daily_lineup(candidates, slots)['starters']:
            player = starter['player']
            planned.update((game, player['player_id']) for game in by_team_day[player['pro_team'], future])
    return planned


def _outcome_probabilities(totals, categories, reverse, tiebreak):
    direction = [-1 if c in reverse else 1 for c in categories]
    stats = category_arrays(totals, categories) * direction
    tie = category_arrays(totals, [tiebreak])[..., 0] * (-1 if tiebreak in reverse else 1) if tiebreak else None
    _, _, _, outcomes = compare_category_trials(stats[0], stats[1], tie[0] if tie is not None else None,
                                               tie[1] if tie is not None else None)
    return [float(np.mean(outcomes == outcome)) for outcome in (1, 0, -1)]


def _timeline(teams, events, observed, plans, start, start_day, distributions, categories, reverse, tiebreak,
              result, trials=TRIALS):
    actual = np.zeros((2, len(COMPONENTS)))
    finished, draws, points = set(), {}, []

    def point(day, at, game_id=None, name=None):
        totals = np.repeat(actual[:, None, :], trials, axis=1)
        for index, tid in enumerate(teams):
            for gid, pid in sorted(plans[day][tid]):
                if gid in finished:
                    continue
                if (gid, pid) not in draws:
                    d = distributions[pid]
                    rng = np.random.default_rng(np.random.SeedSequence([20261116, gid, pid]))
                    draws[gid, pid] = d.samples[rng.choice(len(d.samples), trials, p=d.weights)]
                totals[index] += draws[gid, pid]
        win, tie, loss = _outcome_probabilities(totals, categories, reverse, tiebreak)
        points.append({'at': at.isoformat(), 'day': day, 'game_id': game_id, 'game': name,
                       'p_win': win, 'p_tie': tie, 'p_loss': loss})

    point(start_day, start)
    for game, event in events:
        finished.add(game.id)
        for index, team_id in enumerate(teams):
            for stats in observed[game.id].get(team_id, ()):
                actual[index] += [stats.get(c, 0) for c in COMPONENTS]
        point(game.day, event.at, game.id, event.name)
    if result is not None and events:
        points[-1].update(p_win=float(result == 1), p_tie=float(result == 0), p_loss=float(result == -1), final=True)
    return points


def get_matchup_timeline(metadata, team_id, week, *, now=None):
    league = metadata.league
    now = now or datetime.now(timezone.utc)
    current_week = int(league.currentMatchupPeriod)
    current_day = int(league.scoringPeriodId)
    opponent, outcome = _find_match(metadata, week, team_id)
    if not opponent or week > current_week:
        return {'points': []}
    teams = team_id, opponent
    days = get_matchup_scoring_periods(league, week)
    archived_days = [day for day in days if day <= current_day]
    slots = league_slots(metadata)
    games, by_team_day = _nba_schedule(league, days)
    if not games or not archived_days:
        return {'points': []}
    first_game = min(games.values(), key=lambda game: game.tipoff)
    start = first_game.tipoff - timedelta(seconds=1)
    if start > now:
        return {'points': []}
    bucket = int(now.timestamp() // 60)
    with ThreadPoolExecutor(max_workers=4) as pool:
        requests = {day: pool.submit(_daily_box, league, week, day, bucket if day == current_day else None)
                    for day in archived_days}
        lineups = {day: _day_rosters(job.result(), week, day, teams) for day, job in requests.items()}

    observed, relevant, players = defaultdict(lambda: defaultdict(list)), defaultdict(dict), {}
    for day, lineups_by_team in lineups.items():
        for tid, roster in lineups_by_team.items():
            for player in roster:
                if player['slot'] not in ('IR', 'Rookie'):
                    players[player['player_id']] = player
                if player['slot'] not in slots:
                    continue
                for gid in player['splits'] or by_team_day.get((player['pro_team'], day), ()):
                    relevant[gid][player['player_id']] = player['splits'].get(gid, {})
                for game_id, stats in player['splits'].items():
                    if game_id not in games:
                        raise TimelineUnavailable('ESPN credited game missing from NBA schedule')
                    observed[game_id][tid].append(stats)

    upcoming = [games[gid] for gid in relevant if games[gid].tipoff <= now]
    with ThreadPoolExecutor(max_workers=8) as pool:
        tasks = {g: pool.submit(_finished_game, g.id, bucket if g.day == current_day else None) for g in upcoming}
        events = [(g, task.result()) for g, task in tasks.items()]
    if week < current_week and any(event is None for g, event in events if g.id in observed):
        raise TimelineUnavailable('ESPN historical game completion unavailable')
    events = sorted(((g, e) for g, e in events if e and e.at <= now), key=lambda item: (item[1].at, item[0].id))
    # ESPN may mark an NBA game final before the fantasy box has all the plays.
    for index, (game, event) in enumerate(events):
        if game.day == current_day and any(
            credited.get(c, 0) != event.stats.get(pid, {}).get(c, 0)
            for pid, credited in relevant[game.id].items() for c in COMPONENTS
        ):
            events = events[:index]
            outcome = None
            break
    if not events:
        return {'points': []}
    categories = metadata.get_categories()
    if metadata.scoring_type != 'H2H_MOST_CATEGORIES' or not categories or set(categories) - set(COMPONENTS) - RATIOS.keys():
        raise TimelineUnavailable('This league format is unsupported')
    scoring = (metadata.league_data.get('settings') or {}).get('scoringSettings', {})
    tiebreak = STATS_MAP.get(str(scoring.get('matchupTieRuleBy'))) if scoring.get('matchupTieRule') == 'STAT_POINTS' else None
    if tiebreak and tiebreak not in (*COMPONENTS, *RATIOS):
        raise TimelineUnavailable('This league tiebreak is unsupported')
    distributions, coverage = build_distributions(players.values(), metadata.year, HISTORY, as_of=start, historical=True)
    if not distributions:
        raise TimelineUnavailable('No player history before the matchup')
    start_day = min(lineups)
    plans = {}
    for day in {start_day, *(game.day for game, _ in events)}:
        rostered = {p['player_id']: p for roster in lineups[day].values() for p in roster}
        values = _model_values(rostered, distributions, categories, metadata.reverse_categories)
        plans[day] = {tid: _planned_games(day, lineups[day][tid], days, slots, by_team_day, distributions, values)
                      for tid in teams}
    points = _timeline(teams, events, observed, plans, start, start_day, distributions, categories,
                       metadata.reverse_categories, tiebreak, outcome)
    return {'team_id': team_id, 'opponent_id': opponent, 'points': points,
            'unmodelled_players': sum(not row['games'] for row in coverage)}
