"""Read-only NBA data and weekly roster grids for Bluefin GM."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from threading import Lock
from time import monotonic
from urllib.request import Request, urlopen
from fastapi import APIRouter, Depends, HTTPException, Query
from dependencies import get_league_meta
from core.config import DEFAULT_PERIOD, YEAR
from core.injuries import INJURY_MODE, load_injury_report, nba_date
from core.snapshot import build_league_snapshot
from core.roster_rules import static_roster_mode
from core.projection import build_matchup_lineups, get_matchup_scoring_periods, get_remaining_scoring_periods, has_game, roster_available_on
from services.projections import injury_roster_today, projection_injury_context, projection_snapshot_options, select_projection_roster
from services.season import project_regular_season
from services.live_matchups import current_matchup
from dataclasses import replace
from fastapi import Request as FastAPIRequest
from models import MultiTeamTradeRequest, TradeAnalysisRequest
from services.trade_probability import trade_snapshots
from core.trade_roster import selected_roster_after_trade
from core.z_score import calculate_z_scores
from core.analytics_cache import analytics_version, digest
import math

router = APIRouter(prefix='/api/bluefin', tags=['bluefin'])
_cache, _lock, _pool = {}, Lock(), ThreadPoolExecutor(max_workers=4)


def parse_return_drops(raw):
    try:
        return {int(k): int(v) for k, v in json.loads(raw).items()} if raw else {}
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, 'Неверные правила возврата из IR')


def season_result(meta, period, mode, count, custom_rosters, punts, punt_team_id=None, ir_return_drops=None):
    key = ('season', period, mode, count, analytics_version(meta, injury_aware=mode == INJURY_MODE, live=True),
           tuple(sorted((int(k), tuple(v)) for k, v in custom_rosters.items())), tuple(punts), punt_team_id, tuple(sorted((ir_return_drops or {}).items())))
    with _lock:
        hit = _cache.get(key)
        if hit:
            return hit[1]
    result = project_regular_season(meta, period, simulation_mode=mode, top_n_players=count,
                                    custom_rosters=custom_rosters, punt_categories=punts, record_forecasts=False,
                                    punt_team_id=punt_team_id, ir_return_drops=ir_return_drops)
    with _lock:
        if len(_cache) >= 128:
            _cache.clear()
        _cache[key] = (monotonic(), result)
    return result


@router.get('/season')
def season(period: str = DEFAULT_PERIOD, simulation_mode: str = 'top_n', top_n_players: int = 13,
           custom_team_id: int | None = None, custom_team_players: str = '', punt_categories: str = '', custom_rosters: str = '',
           meta=Depends(get_league_meta), punt_team_id: int | None = None, ir_return_drops: str = ""):
    custom = {custom_team_id: custom_team_players.split(',')} if custom_team_id and custom_team_players else {}
    if custom_rosters:
        try:
            parsed = json.loads(custom_rosters)
            if not isinstance(parsed, dict) or any(not isinstance(v, list) or not all(isinstance(n, str) for n in v) for v in parsed.values()):
                raise ValueError()
            custom.update({int(k): v for k, v in parsed.items()})
        except (ValueError, TypeError):
            raise HTTPException(422, 'Неверный состав')
    return season_result(meta, period, simulation_mode, top_n_players, custom,
                         tuple(filter(None, punt_categories.split(','))), punt_team_id, parse_return_drops(ir_return_drops))


@router.post('/trade')
def trade(body: TradeAnalysisRequest, http_request: FastAPIRequest, meta=Depends(get_league_meta)):
    injury_aware = body.simulation_mode == INJURY_MODE
    version = analytics_version(meta, injury_aware=injury_aware, live=True)
    key = ('trade', version, digest(body.model_dump()))
    with _lock:
        hit = _cache.get(key)
        if hit:
            return hit[1]
    from routers.trades import analyze_trade
    result = analyze_trade(body, http_request, meta)
    custom = body.custom_team_players or {}
    snapshot = build_league_snapshot(meta, body.period, **projection_snapshot_options(body.simulation_mode))
    current = current_matchup(meta, snapshot.current_matchup_period, snapshot.active_slots)
    before = project_regular_season(meta, body.period, simulation_mode=body.simulation_mode,
        top_n_players=body.top_n_players, snapshot_override=snapshot, custom_rosters=custom,
        punt_categories=body.punt_categories, record_forecasts=False, punt_team_id=body.punt_team_id, current=current, ir_return_drops=body.ir_return_drops)
    moved = []
    for player in snapshot.players:
        destination = (body.their_team_id if player.fantasy_team_id == body.my_team_id and player.name in body.i_give else
                       body.my_team_id if player.fantasy_team_id == body.their_team_id and player.name in body.i_receive else None)
        team = meta.get_team_by_id(destination) if destination else None
        moved.append(replace(player, fantasy_team_id=destination, fantasy_team_name=team.team_name,
                             lineup_slot='BE' if injury_aware else player.lineup_slot) if team else player)
    after_snapshot = replace(snapshot, players=tuple(moved))
    after_custom = dict(custom)
    for team_id, give, receive in ((body.my_team_id, body.i_give, body.i_receive), (body.their_team_id, body.i_receive, body.i_give)):
        if team_id in custom:
            after_custom[team_id] = selected_roster_after_trade(custom[team_id], give, receive,
                [p.as_projection_player() for p in after_snapshot.team_players(team_id)], body.top_n_players, body.punt_categories)
    after = project_regular_season(meta, body.period, simulation_mode=body.simulation_mode,
        top_n_players=body.top_n_players, snapshot_override=after_snapshot, custom_rosters=after_custom,
        punt_categories=body.punt_categories, record_forecasts=False, punt_team_id=body.punt_team_id, current=current, ir_return_drops=body.ir_return_drops)
    before_places = {t['team_id']: t['projected_position'] for t in before['standings']}
    after_places = {t['team_id']: t['projected_position'] for t in after['standings']}
    result['simulation_ranks']['calendar'] = {key: {'before': before_places[team_id], 'after': after_places[team_id]}
        for key, team_id in (('my_team', body.my_team_id), ('their_team', body.their_team_id))}
    with _lock:
        if len(_cache) >= 128:
            _cache.clear()
        _cache[key] = (monotonic(), result)
    return result


@router.post('/trade-scenario')
def trade_scenario(body: MultiTeamTradeRequest, http_request: FastAPIRequest, meta=Depends(get_league_meta)):
    from routers.trades import analyze_multi_team_trade

    custom = body.custom_team_players or {}
    try:
        before, after, after_custom = trade_snapshots(meta, {**body.model_dump(), 'custom_rosters': custom})
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    result = analyze_multi_team_trade(body, http_request, meta)
    if 'error' in result:
        return result
    current = current_matchup(meta, before.current_matchup_period, before.active_slots)
    options = dict(simulation_mode=body.simulation_mode, top_n_players=body.top_n_players,
                   punt_categories=body.punt_categories, record_forecasts=False,
                   punt_team_id=body.punt_team_id, current=current, ir_return_drops=body.ir_return_drops)
    places = {}
    for side, snapshot, rosters in [('before', before, custom), ('after', after, after_custom)]:
        standings = project_regular_season(meta, body.period, snapshot_override=snapshot,
                                           custom_rosters=rosters, **options)['standings']
        places[side] = {t['team_id']: t['projected_position'] for t in standings}
    result['simulation_ranks']['calendar'] = {
        t.team_id: {side: ranks[t.team_id] for side, ranks in places.items()} for t in body.trades
    }
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


@router.get('/injuries')
def injuries():
    return load_injury_report()


@router.get('/roster-meta')
def roster_meta(meta=Depends(get_league_meta)):
    return {'players': [{'player_id': getattr(p, 'playerId', None), 'name': p.name,
                         'is_ir': getattr(p, 'lineupSlot', '') == 'IR' or getattr(p, 'slot_position', '') == 'IR',
                         'injury_status': getattr(p, 'injuryStatus', 'ACTIVE'),
                         'expected_return_date': getattr(p, 'expected_return_date', None)}
                        for team in meta.get_teams() for p in meta.get_team_roster(team.team_id)]}


@router.get('/ir-returns/{team_id}')
def ir_returns(team_id: int, period: str = DEFAULT_PERIOD, punt_categories: str = '',
               ir_return_drops: str = '', meta=Depends(get_league_meta)):
    snapshot = build_league_snapshot(meta, period, **projection_snapshot_options(INJURY_MODE))
    context = projection_injury_context(
        meta, snapshot, INJURY_MODE, punt_team_id=team_id,
        punt_categories=tuple(filter(None, punt_categories.split(','))),
        ir_return_drops=parse_return_drops(ir_return_drops),
    )
    _, timeline = context.plan(
        [p.as_projection_player() for p in snapshot.team_players(team_id)], team_id, include_return_steps=True,
    )
    return {'returns': timeline['return_steps'],
            'undated': [player for player in timeline['unavailable'] if player['in_ir']]}


@router.get('/active-rosters')
def active_rosters(period: str = DEFAULT_PERIOD, punt_categories: str = '',
                   punt_team_id: int | None = None, meta=Depends(get_league_meta), ir_return_drops: str = ''):
    rosters = {t.team_id: [] for t in meta.get_teams()}
    for row in injury_roster_today(meta, period, punt_team_id=punt_team_id,
                                  punt_categories=tuple(filter(None, punt_categories.split(','))),
                                  ir_return_drops=parse_return_drops(ir_return_drops)):
        rosters[row['team_id']].append(row['name'])
    return {'rosters': rosters}


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
    simulation_mode = static_roster_mode(simulation_mode)
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
             custom_team_players: str = '', punt_categories: str = '', meta=Depends(get_league_meta),
             punt_team_id: int | None = None, ir_return_drops: str = ""):
    snapshot = build_league_snapshot(meta, period, **projection_snapshot_options(simulation_mode))
    punts = tuple(filter(None, punt_categories.split(',')))
    injury_context = projection_injury_context(meta, snapshot, simulation_mode,
        punt_team_id=punt_team_id, punt_categories=punts, ir_return_drops=parse_return_drops(ir_return_drops))
    timeline = {}
    ps = select_projection_roster([p.as_projection_player() for p in snapshot.team_players(team_id)], simulation_mode,
                                  top_n_players, tuple(filter(None, custom_team_players.split(','))),
                                  injury_context=injury_context, team_id=team_id, timeline=timeline)
    if injury_context and week == snapshot.current_matchup_period:
        days = get_remaining_scoring_periods(meta.league, week)
        ps = [{**p, 'future_only': True, 'as_of': snapshot.created_at} for p in ps]
    else:
        days = get_matchup_scoring_periods(meta.league, week)
    lineups = build_matchup_lineups(ps, days, slots=snapshot.active_slots,
                                  punt_categories=injury_context.punts_for(team_id) if injury_context else punts)
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
    result = {'team_id': team_id, 'week': week, 'days': grid, 'selected_games': lineups['selected_games']}
    if injury_context:
        game_dates = [nba_date(dates[day]) for day in days if day in dates]
        result['roster_players'] = [p['name'] for p in ps
                                    if any(roster_available_on(p, day) for day in game_dates)]
        result['roster_timeline'] = timeline
    return result
