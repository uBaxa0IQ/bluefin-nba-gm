from types import SimpleNamespace

import numpy as np
import pytest

from core.monte_carlo import (COMPONENTS, INDEX, PlayerDistribution, WeekPlan,
                              category_arrays, rank_trial, simulate_seasons)
from web.backend.services.game_history import parse_games
from web.backend.services.monte_carlo import load_inputs, save_inputs


def distribution(*games):
    rows = [[g.get(c, 0) for c in COMPONENTS] for g in games]
    return PlayerDistribution(rows, np.ones(len(rows)))


def teams(n=2):
    return [dict(team_id=i + 1, team_name=f'Team {i + 1}', wins=0, losses=0, ties=0) for i in range(n)]


def run(plans, data, **kwargs):
    return simulate_seasons(teams(), plans, data, categories=['PTS'], playoff_teams=1, trials=500, seed=91, **kwargs)


def test_deterministic_season_keeps_completed_record_and_uses_official_schedule():
    roster = teams(3)
    roster[1]['wins'] = 2
    result = simulate_seasons(roster, [WeekPlan(3, {1: {11: 1}, 2: {22: 1}, 3: {33: 1}}, ((1, 2),))],
                              {11: distribution({'PTS': 10}), 22: distribution({'PTS': 2}), 33: distribution({'PTS': 99})},
                              categories=['PTS'], trials=50, playoff_teams=1)
    by_id = {t['team_id']: t for t in result['standings']}
    assert by_id[1]['expected_record'] == {'wins': 1., 'losses': 0., 'ties': 0.}
    assert by_id[2]['expected_record'] == {'wins': 2., 'losses': 1., 'ties': 0.}
    assert by_id[3]['expected_record'] == {'wins': 0., 'losses': 0., 'ties': 0.}
    assert len(result['weeks'][0]['matchups']) == 3
    assert sum(m['official'] for m in result['weeks'][0]['matchups']) == 1


def test_sampling_whole_games_preserves_category_dependence():
    result = simulate_seasons(teams(), [WeekPlan(1, {1: {11: 1}, 2: {22: 1}}, ((1, 2),))],
                              {11: distribution({'PTS': 10, 'REB': 10}, {'PTS': 0, 'REB': 0}),
                               22: distribution({'PTS': 5, 'REB': 5})},
                              categories=['PTS', 'REB'], trials=5000, seed=42, playoff_teams=1)
    m = result['weeks'][0]['matchups'][0]
    assert .47 < m['p_win'] < .53
    assert m['p_win'] == m['categories']['PTS']['p_win'] == m['categories']['REB']['p_win']
    assert m['p_tie'] == 0


def test_percentages_use_aggregate_shot_components_and_fixed_actual():
    plans = [WeekPlan(1, {1: {11: 1}, 2: {22: 1}}, ((1, 2),),
                      {1: {'FGM': 1, 'FGA': 1}})]
    result = simulate_seasons(teams(), plans, {11: distribution({'FGM': 0, 'FGA': 9}),
                                              22: distribution({'FGM': 2, 'FGA': 5})},
                              categories=['FG%'], trials=30, playoff_teams=1)
    assert result['weeks'][0]['matchups'][0]['p_loss'] == 1


def test_reverse_category_and_ties():
    result = simulate_seasons(teams(), [WeekPlan(1, {1: {11: 1}, 2: {22: 1}}, ((1, 2),))],
                              {11: distribution({'TO': 2}), 22: distribution({'TO': 8})},
                              categories=['TO'], reverse_categories=['TO'], trials=30, playoff_teams=1)
    assert result['weeks'][0]['matchups'][0]['p_win'] == 1
    tied = run([WeekPlan(1, {}, ((1, 2),))], {})
    assert tied['weeks'][0]['matchups'][0]['p_tie'] == 1
    assert all(t['expected_record']['ties'] == 1 for t in tied['standings'])


def test_seed_reproducibility_and_probability_mass():
    plans = [WeekPlan(1, {1: {11: 3}, 2: {22: 3}}, ((1, 2),))]
    data = {11: distribution({'PTS': 1}, {'PTS': 11}), 22: distribution({'PTS': 7})}
    a, b = run(plans, data), run(plans, data)
    assert a == b
    for team in a['standings']:
        assert sum(team['rank_probabilities'].values()) == pytest.approx(1)
    for rank in ('1', '2'):
        assert sum(t['rank_probabilities'][rank] for t in a['standings']) == pytest.approx(1)
    assert sum(t['p_playoffs'] for t in a['standings']) == pytest.approx(1)
    m = a['weeks'][0]['matchups'][0]
    assert m['p_win'] + m['p_tie'] + m['p_loss'] == pytest.approx(1)


def test_h2h_tie_breaker_uses_tied_group_and_restarts():
    rng = np.random.default_rng(1)
    h2h_games = np.ones((3, 3), dtype=int) - np.eye(3, dtype=int)
    # A beats B, B beats C, A beats C; identical overall record.
    h2h = np.array([[0, 2, 2], [0, 0, 2], [0, 0, 0]])
    assert rank_trial(np.array([4, 4, 4]), np.array([4, 4, 4]), h2h, h2h_games, rng) == [0, 1, 2]


def test_unresolved_ties_do_not_favor_team_id():
    result = run([], {})
    for team in result['standings']:
        assert .4 < team['rank_probabilities']['1'] < .6


def test_undefined_ratios_follow_calendar_convention():
    totals = np.zeros((1, len(COMPONENTS)))
    totals[0, INDEX['AST']] = 5
    np.testing.assert_array_equal(category_arrays(totals, ['FG%', 'A/TO']), [[0, 5]])


def test_invalid_inputs_fail_closed():
    with pytest.raises(ValueError, match='scheduled game count'):
        run([WeekPlan(1, {1: {11: -1}}, ((1, 2),))], {})
    with pytest.raises(ValueError, match='official pairs'):
        run([WeekPlan(1, {}, ((1, 2), (1, 2)))], {})
    with pytest.raises(ValueError, match='game weights'):
        PlayerDistribution(np.zeros((1, len(COMPONENTS))), [-1])


def test_game_parser_excludes_dnp_postseason_and_derives_double_double():
    labels = ['MIN', 'PTS', 'REB', 'AST', 'STL', 'BLK', 'TO', 'FG', 'FT', '3PT']
    row = ['32', '22', '10', '2', '1', '0', '3', '8-16', '4-5', '2-6']
    data = {'labels': labels, 'events': {'1': {'gameDate': '2026-11-10T01:00Z'},
                                        '2': {'gameDate': '2026-11-12T01:00Z'}},
            'seasonTypes': [{'displayName': 'Regular Season', 'categories': [{'events': [
                {'eventId': '1', 'stats': row}, {'eventId': '2', 'stats': row, 'didNotPlay': True}]}]},
                            {'displayName': 'Postseason', 'categories': [{'events': [{'eventId': '2', 'stats': row}]}]}]}
    games = parse_games(data)
    assert len(games) == 1
    assert games[0]['stats']['DD'] == 1
    assert games[0]['stats']['FGM'] == 8
    assert games[0]['stats']['3PA'] == 6


def test_frozen_inputs_round_trip(tmp_path):
    prepared = {'teams': teams(), 'weeks': [WeekPlan(1, {1: {11: 2}}, ((1, 2),), {2: {'PTS': 3}})],
                'players': [], 'metadata': {}, 'categories': ['PTS'], 'reverse_categories': [],
                'historical_h2h': [], 'playoff_teams': 1}
    path = tmp_path / 'inputs.json'
    save_inputs(path, prepared, {11: distribution({'PTS': 1}, {'PTS': 10})}, [])
    restored, data = load_inputs(path)
    assert run(prepared['weeks'], {11: distribution({'PTS': 1}, {'PTS': 10})}) == run(restored['weeks'], data)


def test_configured_weekly_tiebreaker_changes_result_without_changing_category_odds():
    result = simulate_seasons(teams(), [WeekPlan(1, {1: {11: 1}, 2: {22: 1}}, ((1, 2),))],
                              {11: distribution({'PTS': 10, 'REB': 1}), 22: distribution({'PTS': 5, 'REB': 3})},
                              categories=['PTS', 'REB'], matchup_tie_category='PTS', trials=10, playoff_teams=1)
    match = result['weeks'][0]['matchups'][0]
    assert match['expected_categories'] == [1., 1.]
    assert match['p_win'] == 1
    assert match['categories']['REB']['p_loss'] == 1


def test_calendar_adapter_freezes_legal_lineup_and_keeps_injured_selected_players(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from core.snapshot import LeagueSnapshot, PlayerSnapshot
    from web.backend.services import monte_carlo as adapter

    now = datetime.now(timezone.utc)
    def player(pid, team, z):
        return PlayerSnapshot(pid, str(pid), team, str(team), 'PG', ('UT',), 'BE', True, 'OUT', None,
                              {str(w): {'date': now + timedelta(days=w)} for w in (2, 3)},
                              {'PTS': z}, {'PTS': z})
    snapshot = LeagueSnapshot('test', now, 2, 2, (player(11, 1, 10), player(12, 1, 1), player(22, 2, 5)), {}, ('UT',))
    raw = {'settings': {'scheduleSettings': {'divisions': [{'id': 0}], 'playoffSeedingRule': 'H2H_RECORD'}},
           'schedule': [{'matchupPeriodId': w, 'home': {'teamId': 1}, 'away': {'teamId': 2}} for w in (1, 2, 3)]}
    metadata = SimpleNamespace(
        league=SimpleNamespace(currentMatchupPeriod=2, settings=SimpleNamespace(reg_season_count=3, playoff_team_count=1),
                               espn_request=SimpleNamespace(get_league=lambda: raw)),
        get_teams=lambda: [SimpleNamespace(team_id=1, team_name='A', wins=1, losses=0, ties=0),
                           SimpleNamespace(team_id=2, team_name='B', wins=0, losses=1, ties=0)],
        get_all_teams_stats_for_week=lambda w: {1: {'stats': {'PTS': 10}}, 2: {'stats': {'PTS': 5}}},
        get_matchup_box_score=lambda w, t: {'totals': {}}, get_categories=lambda: ['PTS'],
        reverse_categories=set(), scoring_type='H2H_MOST_CATEGORIES', league_id=1, year=2027)
    monkeypatch.setattr(adapter, 'get_matchup_scoring_periods', lambda league, w: [w])
    monkeypatch.setattr(adapter, 'get_remaining_scoring_periods', lambda league, w: [w])
    plan = adapter.prepare_season(metadata, 'test', snapshot=snapshot)
    assert plan['weeks'][0].games == {1: {11: 1}, 2: {22: 1}}
    assert plan['weeks'][1].games == {1: {11: 1}, 2: {22: 1}}
    assert plan['historical_h2h'] == [(1, 2, 1)]
    assert snapshot.players[0].injured is True
    assert len(snapshot.players) == 3
    # Missing shot denominators must not silently discard current-week actual stats.
    metadata.get_matchup_box_score = lambda w, t: {'totals': {'PTS': 10, 'FG%': .5}}
    with pytest.raises(ValueError, match='shot components missing'):
        adapter.prepare_season(metadata, 'test', snapshot=snapshot)
