"""Paired season and playoff forecasts for a proposed two-team trade."""
from dataclasses import asdict, replace
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
from core.injuries import INJURY_MODE
from .projections import projection_snapshot_options
from .live_matchups import current_matchup

_before_cache = {}


def category_probabilities(forecast):
    """Average category win chance against each team's remaining official opponents."""
    samples = {t['team_id']: {cat: [] for cat in forecast['categories']} for t in forecast['standings']}
    for week in forecast['weeks']:
        for match in week['matchups']:
            if not match['official']:
                continue
            for cat, odds in match['categories'].items():
                samples[match['team1_id']][cat].append(odds['p_win'])
                samples[match['team2_id']][cat].append(odds['p_loss'])
    return [{**team, 'category_probabilities': {
        cat: sum(values) / len(values) if values else None
        for cat, values in samples[team['team_id']].items()}} for team in forecast['standings']]


def trade_matchup_probabilities(forecast, standings):
    by_id = {team['team_id']: team for team in standings}
    postseason = forecast.get('postseason')
    playoff_teams = {team['team_id']: team for team in postseason['teams']} if postseason else {}
    for team_id, team in by_id.items():
        playoff_team = playoff_teams.get(team_id, {})
        team.update(p_final=playoff_team.get('p_final'), p_title=playoff_team.get('p_title'),
                    regular_matchups=[], playoff_matchups=[] if postseason else None)

    for week in forecast['weeks']:
        for match in week['matchups']:
            if match['official']:
                a, b = match['team1_id'], match['team2_id']
                by_id[a]['regular_matchups'].append(dict(week=week['week'], opponent_id=b, p_win=match['p_win']))
                by_id[b]['regular_matchups'].append(dict(week=week['week'], opponent_id=a, p_win=match['p_loss']))

    for round_ in postseason['rounds'] if postseason else ():
        rounds = {team_id: dict(week=round_['week'], start=round_['start'], end=round_['end'], opponents=[])
                  for team_id in by_id}
        for match in round_['matchups']:
            if match['bracket'] == 'championship':
                rounds[match['team_id']]['opponents'].append(
                    {key: match[key] for key in ('opponent_id', 'p_meet', 'p_win')})
        for team_id, round_data in rounds.items():
            by_id[team_id]['playoff_matchups'].append(round_data)
    return standings


def trade_snapshots(metadata, params):
    mode = params.get('simulation_mode', 'top_n')
    snapshot = build_league_snapshot(metadata, params['period'], **projection_snapshot_options(mode))
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
        moved.append(replace(player, fantasy_team_id=destination, fantasy_team_name=names[destination],
                             lineup_slot='BE' if mode == INJURY_MODE else player.lineup_slot)
                     if destination is not None else player)
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
    if 'punt_team_id' in params:
        common['punt_team_id'] = params['punt_team_id']
    live = current_matchup(metadata, before_snapshot.current_matchup_period, before_snapshot.active_slots)
    before = prepare_season(metadata, **common, custom_rosters=params['custom_rosters'],
                            snapshot=before_snapshot, live_matchup=live, include_postseason=True)
    after = prepare_season(metadata, **common, custom_rosters=after_custom,
                           snapshot=after_snapshot, live_matchup=live, include_postseason=True)
    players = {p['player_id']: p for plan in (before, after) for p in plan['players']}
    progress('histories', 0, len(players))
    distributions, _ = build_distributions(list(players.values()), metadata.year,
        ROOT / '.cache' / 'monte_carlo' / 'game_logs', as_of=datetime.fromisoformat(before['metadata']['as_of']),
        excluded_events=before['excluded_events'],
        progress=lambda done, total: progress('histories', done, total))
    ids = {params['my_team_id'], params['their_team_id']}
    result = {'trials': 3000, 'before': None, 'after': None}
    if params['simulation_mode'] == INJURY_MODE:
        result['roster_timelines'] = {label: plan['metadata']['roster_timelines']
                                      for label, plan in (('before', before), ('after', after))}
    # Share baseline category probabilities and standings across trade proposals.
    cache_key = hashlib.sha256(json.dumps([metadata.league_id, metadata.year,
        analytics_version(metadata, stochastic=True, injury_aware=common['simulation_mode'] == INJURY_MODE),
        asdict(before['weeks'][0]) if before['weeks'] else None,
        common, params['custom_rosters'], before.get('postseason') is not None,
        params.get('seed', 20261116)], sort_keys=True).encode()).hexdigest()
    for label, prepared in (('before', before), ('after', after)):
        progress(label, 0, 3000, dict(result))
        standings = _before_cache.get(cache_key) if label == 'before' else None
        if standings is None:
            forecast = simulate_seasons(prepared['teams'], prepared['weeks'], distributions,
                categories=prepared['categories'], reverse_categories=prepared['reverse_categories'],
                historical_h2h=prepared['historical_h2h'], playoff_teams=prepared['playoff_teams'],
                matchup_tie_category=prepared.get('matchup_tie_category'), trials=3000, seed=params.get('seed', 20261116),
                all_opponents=False, paired_draws=True, postseason=prepared.get('postseason'))
            standings = trade_matchup_probabilities(forecast, category_probabilities(forecast))
            if label == 'before':
                _before_cache[cache_key] = standings
                if len(_before_cache) > 4:
                    del _before_cache[next(iter(_before_cache))]
        result[label] = [team for team in standings if team['team_id'] in ids]
    result['elapsed_seconds'] = round(perf_counter() - started, 2)
    return result


trade_probability_jobs = ProbabilityJobs(ROOT / '.cache' / 'trade_probability', runner=run_trade_probability,
                                       cache_revision='trade-matchups-v1')
