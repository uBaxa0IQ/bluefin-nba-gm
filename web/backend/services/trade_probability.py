"""Paired regular-season forecasts for a proposed two-team trade."""
from dataclasses import replace
from datetime import datetime
from time import perf_counter
import hashlib
import json

from core.snapshot import build_league_snapshot
from core.trade_roster import selected_roster_after_trade, validate_ownership
from core.monte_carlo import simulate_seasons
from .monte_carlo import prepare_season
from .game_history import build_distributions
from .probability_jobs import ProbabilityJobs, ROOT
from core.analytics_cache import analytics_version

_before_cache = {}


def trade_snapshots(metadata, params):
    snapshot = build_league_snapshot(metadata, params['period'])
    a, b = params['my_team_id'], params['their_team_id']
    give, receive = params['i_give'], params['i_receive']
    if a == b or not give or not receive:
        raise ValueError('Выберите две команды и игроков для обмена')
    ownership = {t.team_id: {p.name for p in snapshot.team_players(t.team_id)} for t in metadata.get_teams()}
    if set(params['custom_rosters']) - ownership.keys():
        raise ValueError('Неизвестная команда')
    validate_ownership(ownership, {a: {'give': give, 'receive': receive}, b: {'give': receive, 'receive': give}})
    names = {t.team_id: t.team_name for t in metadata.get_teams()}
    moved = []
    for player in snapshot.players:
        destination = b if player.fantasy_team_id == a and player.name in give else a if player.fantasy_team_id == b and player.name in receive else None
        moved.append(replace(player, fantasy_team_id=destination, fantasy_team_name=names[destination]) if destination is not None else player)
    after = replace(snapshot, players=tuple(moved))
    custom = params['custom_rosters']
    after_custom = dict(custom)
    for team, outgoing, incoming in ((a, give, receive), (b, receive, give)):
        if team in custom:
            after_custom[team] = selected_roster_after_trade(custom[team], outgoing, incoming,
                [p.as_projection_player() for p in after.team_players(team)], params['top_n_players'], params['punt_categories'])
    return snapshot, after, after_custom


def run_trade_probability(metadata, params, progress):
    started = perf_counter()
    progress('calendar', 0, 2)
    before_snapshot, after_snapshot, after_custom = trade_snapshots(metadata, params)
    common = {k: params[k] for k in ('period', 'simulation_mode', 'top_n_players', 'punt_categories')}
    before = prepare_season(metadata, **common, custom_rosters=params['custom_rosters'], snapshot=before_snapshot)
    after = prepare_season(metadata, **common, custom_rosters=after_custom, snapshot=after_snapshot)
    players = {p['player_id']: p for plan in (before, after) for p in plan['players']}
    progress('histories', 0, len(players))
    distributions, _ = build_distributions(list(players.values()), metadata.year,
        ROOT / '.cache' / 'monte_carlo' / 'game_logs', as_of=datetime.fromisoformat(before['metadata']['as_of']),
        progress=lambda done, total: progress('histories', done, total))
    ids = {params['my_team_id'], params['their_team_id']}
    result = {'trials': 3000, 'before': None, 'after': None}
    # Baseline is shared across trade proposals, but never across data refreshes.
    cache_key = hashlib.sha256(json.dumps([metadata.league_id, metadata.year,
        analytics_version(metadata, stochastic=True), common, params['custom_rosters']], sort_keys=True).encode()).hexdigest()
    for label, prepared in (('before', before), ('after', after)):
        progress(label, 0, 3000, dict(result))
        standings = _before_cache.get(cache_key) if label == 'before' else None
        if standings is None:
            forecast = simulate_seasons(prepared['teams'], prepared['weeks'], distributions,
                categories=prepared['categories'], reverse_categories=prepared['reverse_categories'],
                historical_h2h=prepared['historical_h2h'], playoff_teams=prepared['playoff_teams'],
                matchup_tie_category=prepared.get('matchup_tie_category'), trials=3000, seed=20261116,
                all_opponents=False, paired_draws=True)
            standings = forecast['standings']
            if label == 'before':
                _before_cache[cache_key] = standings
                if len(_before_cache) > 4:
                    del _before_cache[next(iter(_before_cache))]
        result[label] = [team for team in standings if team['team_id'] in ids]
    result['elapsed_seconds'] = round(perf_counter() - started, 2)
    return result


trade_probability_jobs = ProbabilityJobs(ROOT / '.cache' / 'trade_probability', runner=run_trade_probability)
