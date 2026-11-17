"""Read-only NBA data and weekly roster grids for Bluefin GM."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import re
from threading import Lock
from time import monotonic
from urllib.request import Request, urlopen
from fastapi import APIRouter, Depends, HTTPException, Query
from dependencies import get_league_meta
from core.config import DEFAULT_PERIOD, YEAR
from core.snapshot import build_league_snapshot
from core.projection import build_matchup_lineups, get_matchup_scoring_periods, has_game
from services.projections import select_projection_roster
from services.season import project_regular_season
from dataclasses import replace
from fastapi import Request as FastAPIRequest
from models import TradeAnalysisRequest
from core.trade_roster import selected_roster_after_trade
from core.z_score import calculate_z_scores
from core.analytics_cache import analytics_version, digest
import math

router = APIRouter(prefix='/api/bluefin', tags=['bluefin'])
_cache, _lock, _pool = {}, Lock(), ThreadPoolExecutor(max_workers=4)


def season_result(meta, period, mode, count, custom_rosters, punts):
    key = ('season', period, mode, count, analytics_version(meta),
           tuple(sorted((int(k), tuple(v)) for k, v in custom_rosters.items())), tuple(punts))
    with _lock:
        hit = _cache.get(key)
        if hit:
            return hit[1]
    result = project_regular_season(meta, period, simulation_mode=mode, top_n_players=count,
                                    custom_rosters=custom_rosters, punt_categories=punts, record_forecasts=False)
    with _lock:
        if len(_cache) >= 128:
            _cache.clear()
        _cache[key] = (monotonic(), result)
    return result


@router.get('/season')
def season(period: str = DEFAULT_PERIOD, simulation_mode: str = 'top_n', top_n_players: int = 13,
           custom_team_id: int | None = None, custom_team_players: str = '', punt_categories: str = '', custom_rosters: str = '',
           meta=Depends(get_league_meta)):
    custom = {custom_team_id: custom_team_players.split(',')} if custom_team_id and custom_team_players else {}
    if custom_rosters:
        try:
            parsed = json.loads(custom_rosters)
            if not isinstance(parsed, dict) or any(not isinstance(v, list) or not all(isinstance(n, str) for n in v) for v in parsed.values()):
                raise ValueError()
            custom.update({int(k): v for k, v in parsed.items()})
        except (ValueError, TypeError):
            raise HTTPException(422, 'Неверный состав')
    return season_result(meta, period, simulation_mode, top_n_players, custom, tuple(filter(None, punt_categories.split(','))))


@router.post('/trade')
def trade(body: TradeAnalysisRequest, http_request: FastAPIRequest, meta=Depends(get_league_meta)):
    key = ('trade', analytics_version(meta), digest(body.model_dump()))
    with _lock:
        hit = _cache.get(key)
        if hit:
            return hit[1]
    from routers.trades import analyze_trade
    result = analyze_trade(body, http_request, meta)
    custom = body.custom_team_players or {}
    before = season_result(meta, body.period, body.simulation_mode, body.top_n_players, custom, tuple(body.punt_categories))
    snapshot = build_league_snapshot(meta, body.period)
    moved = []
    for player in snapshot.players:
        destination = (body.their_team_id if player.fantasy_team_id == body.my_team_id and player.name in body.i_give else
                       body.my_team_id if player.fantasy_team_id == body.their_team_id and player.name in body.i_receive else None)
        team = meta.get_team_by_id(destination) if destination else None
        moved.append(replace(player, fantasy_team_id=destination, fantasy_team_name=team.team_name) if team else player)
    after_snapshot = replace(snapshot, players=tuple(moved))
    after_custom = dict(custom)
    for team_id, give, receive in ((body.my_team_id, body.i_give, body.i_receive), (body.their_team_id, body.i_receive, body.i_give)):
        if team_id in custom:
            after_custom[team_id] = selected_roster_after_trade(custom[team_id], give, receive,
                [p.as_projection_player() for p in after_snapshot.team_players(team_id)], body.top_n_players, body.punt_categories)
    after = project_regular_season(meta, body.period, simulation_mode=body.simulation_mode,
        top_n_players=body.top_n_players, snapshot_override=after_snapshot, custom_rosters=after_custom,
        punt_categories=body.punt_categories, record_forecasts=False)
    before_places = {t['team_id']: t['projected_position'] for t in before['standings']}
    after_places = {t['team_id']: t['projected_position'] for t in after['standings']}
    result['simulation_ranks']['calendar'] = {key: {'before': before_places[team_id], 'after': after_places[team_id]}
        for key, team_id in (('my_team', body.my_team_id), ('their_team', body.their_team_id))}
    with _lock:
        if len(_cache) >= 128:
            _cache.clear()
        _cache[key] = (monotonic(), result)
    return result


def espn(url, ttl=600):
    with _lock:
        cached = _cache.get(url)
        if cached and monotonic() - cached[0] < ttl:
            return cached[1]
    try:
        with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=18) as response:
            data = json.load(response)
    except Exception as error:
        raise HTTPException(502, 'Не удалось получить данные ESPN') from error
    with _lock:
        if len(_cache) > 1500:
            _cache.clear()
        _cache[url] = (monotonic(), data)
    return data


def health_record(item):
    athlete, details = item.get('athlete') or {}, item.get('details') or {}
    player_id = athlete.get('id')
    for link in athlete.get('links', []) if not player_id else []:
        match = re.search(r'/id/(\d+)', link.get('href', ''))
        if match:
            player_id = match[1]
            break
    text = ' '.join(str(item.get(k) or '') for k in ('longComment', 'shortComment')).lower()
    season_out = bool(re.search(r'season[- ]ending|out for (?:the|this) season|miss (?:the )?(?:entire|rest of|remainder of) (?:the )?(?:\d{4}[-/]\d{2,4} )?season|won.t (?:play|return)[^.]*?(?:this|the) season', text))
    return_date, long_term = details.get('returnDate'), season_out
    if return_date:
        try:
            long_term |= (datetime.fromisoformat(return_date[:10]).date() - datetime.now(timezone.utc).date()).days >= 30
        except ValueError:
            pass
    status = item.get('status', '').lower()
    return {'player_id': int(player_id) if player_id else None, 'name': athlete.get('displayName'),
            'injury_status': 'OUT' if status == 'out' else 'DTD' if status in ('day-to-day', 'questionable', 'doubtful') else status.upper() or 'UNKNOWN',
            'expected_return_date': return_date, 'out_for_season': season_out, 'long_term': bool(long_term),
            'injury_detail': details.get('type'), 'injury_updated_at': item.get('date')}


@router.get('/injuries')
def injuries():
    data = espn('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries')
    return {'players': [health_record(i) for team in data.get('injuries', []) for i in team.get('injuries', [])],
            'updated_at': data.get('timestamp')}


@router.get('/roster-meta')
def roster_meta(meta=Depends(get_league_meta)):
    return {'players': [{'player_id': getattr(p, 'playerId', None), 'name': p.name,
                         'is_ir': getattr(p, 'lineupSlot', '') == 'IR' or getattr(p, 'slot_position', '') == 'IR',
                         'injury_status': getattr(p, 'injuryStatus', 'ACTIVE'),
                         'expected_return_date': getattr(p, 'expected_return_date', None)}
                        for team in meta.get_teams() for p in meta.get_team_roster(team.team_id)]}


@router.get('/matchups')
def matchups(week: int = Query(ge=1), meta=Depends(get_league_meta)):
    return {'week': week, 'matchups': meta.get_matchups_with_scores(week)}


def _regular_groups(data):
    groups = data.get('seasonTypes', [])
    regular = [g for g in groups if 'regular' in g.get('displayName', '').lower()]
    return regular if regular else [g for g in groups if not any(name in g.get('displayName', '').lower().replace('-', '') for name in ('preseason', 'postseason', 'playoff', 'all star'))]


def event_starters(event_id):
    try:
        data = espn(f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event_id}', 86400)
        return {str(row['athlete']['id']): {'starter': row.get('starter'), 'did_not_play': row.get('didNotPlay', False)}
                for team in data.get('boxscore', {}).get('players', [])
                for group in team.get('statistics', []) for row in group.get('athletes', [])}
    except HTTPException:
        return {}


@router.get('/player/{player_id}/logs')
def logs(player_id: int, season: int = YEAR, offset: int = Query(0, ge=0), limit: int = Query(15, ge=1, le=30)):
    data = espn(f'https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{player_id}/gamelog?season={season}', 1800)
    rows = {}
    for group in _regular_groups(data):
        for category in group.get('categories', []):
            for entry in category.get('events', []):
                event_id = str(entry['eventId'])
                event = data.get('events', {}).get(event_id, {})
                opponent, result = event.get('opponent') or {}, event.get('gameResult') or {}
                rows[event_id] = {'event_id': event_id, 'date': event.get('gameDate'),
                                  'opponent': opponent.get('abbreviation') or opponent.get('displayName'),
                                  'home_away': event.get('atVs'),
                                  'result': (result.get('displayValue') or result.get('value')) if isinstance(result, dict) else result,
                                  'stats': dict(zip(data.get('labels', []), entry.get('stats', [])))}
    ordered = sorted(rows.values(), key=lambda r: r.get('date') or '', reverse=True)
    page = ordered[offset:offset + limit]
    for row, flags in zip(page, _pool.map(event_starters, [row['event_id'] for row in page])):
        row.update(flags.get(str(player_id), {'starter': None, 'did_not_play': False}))
    return {'player_id': player_id, 'season': season, 'games': page, 'total': len(ordered), 'offset': offset}


def _number(value):
    try:
        number = float(str(value).replace('%', ''))
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _game_stats(values):
    result = {key: _number(values.get(key)) for key in ('MIN', 'PTS', 'REB', 'AST', 'STL', 'BLK', 'TO')}
    for label, makes, attempts in (('FG', 'FGM', 'FGA'), ('FT', 'FTM', 'FTA'), ('3PT', '3PM', '3PA')):
        parts = str(values.get(label, '')).split('-')
        result[makes] = _number(parts[0]) if len(parts) == 2 else None
        result[attempts] = _number(parts[1]) if len(parts) == 2 else None
    for label, numerator, denominator in (('FG%', 'FGM', 'FGA'), ('FT%', 'FTM', 'FTA'), ('3PT%', '3PM', '3PA'), ('A/TO', 'AST', 'TO')):
        a, b = result.get(numerator), result.get(denominator)
        result[label] = a / b if a is not None and b else None
    result['DD'] = float(sum((result.get(k) or 0) >= 10 for k in ('PTS', 'REB', 'AST', 'STL', 'BLK')) >= 2)
    return result


@router.get('/player/{player_id}/analytics')
def player_analytics(player_id: int, season: int = YEAR):
    data = espn(f'https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{player_id}/gamelog?season={season}', 1800)
    games = {}
    for group in _regular_groups(data):
        for category in group.get('categories', []):
            for entry in category.get('events', []):
                event_id = str(entry['eventId'])
                event = data.get('events', {}).get(event_id, {})
                raw = dict(zip(data.get('labels', []), entry.get('stats', [])))
                stats = _game_stats(raw)
                opponent = event.get('opponent') or {}
                games[event_id] = {'event_id': event_id, 'date': event.get('gameDate'),
                    'opponent': opponent.get('abbreviation') or opponent.get('displayName'),
                    'did_not_play': bool(entry.get('didNotPlay')) or stats.get('MIN') is None or stats.get('MIN') == 0,
                    'stats': stats}
    return {'player_id': player_id, 'season': season,
            'games': sorted(games.values(), key=lambda g: g.get('date') or ''), 'total': len(games)}


@router.get('/form/{team_id}')
def team_form(team_id: int, simulation_mode: str = 'top_n', top_n_players: int = 13,
              custom_team_players: str = '', punt_categories: str = '', meta=Depends(get_league_meta)):
    from core.config import PERIODS
    names, excluded = set(filter(None, custom_team_players.split(','))), set(filter(None, punt_categories.split(',')))
    result = []
    for key in ('total', 'last_30', 'last_15', 'last_7'):
        data = calculate_z_scores(meta, PERIODS[key], exclude_ir=simulation_mode == 'exclude_ir')
        ps = [p for p in data['players'] if p['team_id'] == team_id]
        if simulation_mode == 'top_n':
            ps = [p for p in ps if p['name'] in names] if names else sorted(ps, key=lambda p: sum(v for c, v in p['z_scores'].items() if c not in excluded and math.isfinite(v)), reverse=True)[:top_n_players]
        value = sum(v for p in ps for c, v in p['z_scores'].items() if c not in excluded and math.isfinite(v))
        result.append({'key': key, 'value': round(value, 2)})
    return {'periods': result}


@router.get('/calendar/{team_id}')
def calendar(team_id: int, week: int = Query(ge=1), period: str = DEFAULT_PERIOD,
             simulation_mode: str = 'top_n', top_n_players: int = 13,
             custom_team_players: str = '', punt_categories: str = '', meta=Depends(get_league_meta)):
    snapshot = build_league_snapshot(meta, period)
    ps = select_projection_roster([p.as_projection_player() for p in snapshot.team_players(team_id)], simulation_mode,
                                  top_n_players, tuple(filter(None, custom_team_players.split(','))))
    days = get_matchup_scoring_periods(meta.league, week)
    lineups = build_matchup_lineups(ps, days, slots=snapshot.active_slots,
                                  punt_categories=tuple(filter(None, punt_categories.split(','))))
    dates = {}
    for team_games in (getattr(meta.league, 'pro_schedule', {}) or {}).values():
        for day, games in team_games.items():
            for game in games:
                if game.get('date'):
                    dates[int(day)] = datetime.fromtimestamp(game['date']/1000, timezone(timedelta(hours=-5))).date().isoformat()
    grid = []
    opponents = {}
    calendar_dates = [dates[d] for d in days if d in dates]
    if calendar_dates:
        date_range = min(calendar_dates).replace('-', '') + '-' + max(calendar_dates).replace('-', '')
        try:
            scoreboard = espn('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=' + date_range + '&limit=1000', 3600)
            for event in scoreboard.get('events', []):
                game_date = datetime.fromisoformat(event['date'].replace('Z', '+00:00')).astimezone(timezone(timedelta(hours=-5))).date().isoformat()
                for competition in event.get('competitions', []):
                    competitors = competition.get('competitors', [])
                    if len(competitors) == 2:
                        for own, other in (competitors, competitors[::-1]):
                            opponents[(game_date, own['team']['abbreviation'])] = ('vs ' if own.get('homeAway') == 'home' else '@ ') + other['team']['abbreviation']
        except HTTPException:
            pass
    team_abbreviations = {p.name: p.pro_team for p in snapshot.team_players(team_id)}
    for day in lineups['days']:
        starters = {entry['player']['name']: entry['slot'] for entry in day['starters']}
        grid.append({'scoring_period': day['scoring_period'], 'date': dates.get(day['scoring_period']),
                     'players': [{'name': p['name'], 'playing': has_game(p, day['scoring_period']), 'slot': starters.get(p['name']),
                                  'opponent': opponents.get((dates.get(day['scoring_period']), team_abbreviations.get(p['name']))),
                                  'game': (p.get('schedule') or {}).get(str(day['scoring_period']), (p.get('schedule') or {}).get(day['scoring_period']))}
                                 for p in ps]})
    return {'team_id': team_id, 'week': week, 'days': grid, 'selected_games': lineups['selected_games']}
