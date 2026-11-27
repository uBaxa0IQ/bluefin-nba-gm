"""Leave-one-player-out forecasts with fixed lineups and paired player draws."""
from dataclasses import replace
from datetime import datetime
from time import perf_counter

from core.snapshot import build_league_snapshot
from core.monte_carlo import simulate_seasons
from .monte_carlo import prepare_season
from .game_history import build_distributions
from .probability_jobs import ProbabilityJobs, ROOT
from .projections import projection_snapshot_options


def without_player(weeks, team_id, player_id):
    # No replacement: other starters and already credited totals stay fixed.
    return [replace(week,
        games={**week.games, team_id: {pid: n for pid, n in week.games.get(team_id, {}).items() if pid != player_id}},
        live_games={**week.live_games, team_id: {pid: game for pid, game in week.live_games.get(team_id, {}).items()
                                              if pid != player_id}}) for week in weeks]


def team_forecast(forecast, team_id):
    standing = next(t for t in forecast['standings'] if t['team_id'] == team_id)
    weeks = []
    for week in forecast['weeks']:
        for match in week['matchups']:
            if not match['official'] or team_id not in (match['team1_id'], match['team2_id']):
                continue
            home = match['team1_id'] == team_id
            weeks.append({'week': week['week'],
                'opponent_id': match['team2_id'] if home else match['team1_id'],
                'p_win': match['p_win'] if home else match['p_loss'],
                'categories': {cat: p['p_win'] if home else p['p_loss'] for cat, p in match['categories'].items()}})
    return {'standing': standing, 'weeks': weeks}


def contribution_row(player, baseline, removed, games):
    omitted = {w['week']: w for w in removed['weeks']}
    weeks = [{**week, 'without_p_win': omitted[week['week']]['p_win'],
        'win_delta': week['p_win'] - omitted[week['week']]['p_win'],
        'category_deltas': {cat: p - omitted[week['week']]['categories'][cat]
                            for cat, p in week['categories'].items()}} for week in baseline['weeks']]
    cats = next(iter(weeks), {}).get('categories', {})
    return {'player_id': player.player_id, 'name': player.name, 'games': games,
        'category_deltas': {cat: sum(w['category_deltas'][cat] for w in weeks) / len(weeks) for cat in cats},
        'win_delta': sum(w['win_delta'] for w in weeks),
        'playoff_delta': baseline['standing']['p_playoffs'] - removed['standing']['p_playoffs'],
        'rank_delta': removed['standing']['expected_rank'] - baseline['standing']['expected_rank'],
        'without': removed['standing'], 'weeks': weeks}


def run_contribution(metadata, params, progress):
    started = perf_counter()
    team_id = params['team_id']
    snapshot = build_league_snapshot(metadata, params['period'], **projection_snapshot_options(params['simulation_mode']))
    roster = snapshot.team_players(team_id)
    progress('calendar', 0, len(roster))
    prepared = prepare_season(metadata, params['period'], simulation_mode=params['simulation_mode'],
        top_n_players=params['top_n_players'], custom_rosters=params['custom_rosters'],
        punt_categories=params['punt_categories'], snapshot=snapshot, punt_team_id=params.get('punt_team_id'),
        ir_return_drops={int(k): v for k, v in params.get('ir_return_drops', {}).items()})
    distributions, _ = build_distributions(prepared['players'], metadata.year,
        ROOT / '.cache' / 'monte_carlo' / 'game_logs', as_of=datetime.fromisoformat(prepared['metadata']['as_of']),
        excluded_events=prepared['excluded_events'],
        progress=lambda done, total: progress('histories', done, total))

    def simulate(plans):
        return team_forecast(simulate_seasons(prepared['teams'], plans, distributions,
            categories=prepared['categories'], reverse_categories=prepared['reverse_categories'],
            historical_h2h=prepared['historical_h2h'], playoff_teams=prepared['playoff_teams'],
            matchup_tie_category=prepared.get('matchup_tie_category'), trials=3000,
            seed=params['seed'], all_opponents=False, paired_draws=True), team_id)

    progress('baseline', 0, len(roster))
    baseline = simulate(prepared['weeks'])
    result = {'team_id': team_id, 'trials': 3000, 'categories': prepared['categories'],
        'baseline': baseline, 'players': [], 'metadata': prepared['metadata']}
    for i, player in enumerate(roster):
        games = sum(w.games.get(team_id, {}).get(player.player_id, 0) for w in prepared['weeks'])
        has_remainder = any(player.player_id in week.live_games.get(team_id, {}) for week in prepared['weeks'])
        removed = simulate(without_player(prepared['weeks'], team_id, player.player_id)) if games or has_remainder else baseline
        row = contribution_row(player, baseline, removed, games)
        result = {**result, 'players': [*result['players'], row]}
        progress('players', i + 1, len(roster), result)
    return {**result, 'elapsed_seconds': round(perf_counter() - started, 2)}


contribution_jobs = ProbabilityJobs(ROOT / '.cache' / 'roster_contribution', runner=run_contribution)
