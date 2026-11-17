from types import SimpleNamespace

import numpy as np
import pytest

from core.monte_carlo import COMPONENTS, PlayerDistribution, WeekPlan, simulate_seasons
from web.backend.services.roster_contribution import without_player, team_forecast, contribution_row


def test_removal_preserves_other_starters_and_current_week_credited_totals():
    plans = [WeekPlan(5, {1: {11: 3, 12: 2}, 2: {22: 4}}, ((1, 2),), {1: {'PTS': 70}})]
    removed = without_player(plans, 1, 11)
    assert removed[0].games == {1: {12: 2}, 2: {22: 4}}
    assert removed[0].actual == {1: {'PTS': 70}}
    assert plans[0].games[1][11] == 3
    assert without_player(plans, 2, 11)[0].games == plans[0].games


def test_away_team_effect_uses_own_win_probabilities_and_expected_wins():
    teams = [dict(team_id=i, team_name=str(i), wins=0, losses=0, ties=0) for i in (1, 2)]
    def dist(pts):
        return PlayerDistribution([[pts if c == 'PTS' else 0 for c in COMPONENTS]], np.ones(1))
    plans = [WeekPlan(1, {1: {11: 1}, 2: {22: 1}}, ((1, 2),))]
    def run(weeks):
        return team_forecast(simulate_seasons(teams, weeks, {11: dist(5), 22: dist(10)},
            categories=['PTS'], playoff_teams=1, trials=30, paired_draws=True), 2)
    base, removed = run(plans), run(without_player(plans, 2, 22))
    row = contribution_row(SimpleNamespace(player_id=22, name='A'), base, removed, 1)
    assert row['win_delta'] == 1
    assert row['category_deltas'] == {'PTS': 1}
    assert row['playoff_delta'] == 1
    assert row['rank_delta'] == 1
    assert row['weeks'][0]['opponent_id'] == 1
    assert row['weeks'][0]['without_p_win'] == 0
    zero = contribution_row(SimpleNamespace(player_id=99, name='Bench'), base, base, 0)
    assert zero['win_delta'] == zero['playoff_delta'] == zero['rank_delta'] == 0


def test_category_effect_averages_matchups_but_wins_sum_them():
    standing = {'p_playoffs': .6, 'expected_rank': 4}
    base = {'standing': standing, 'weeks': [{'week': w, 'opponent_id': 2, 'p_win': .7,
            'categories': {'PTS': .8, 'FT%': .3}} for w in (5, 6)]}
    removed = {'standing': {'p_playoffs': .5, 'expected_rank': 5}, 'weeks': [
        {'week': w, 'p_win': .5, 'categories': {'PTS': .5, 'FT%': .4}} for w in (5, 6)]}
    row = contribution_row(SimpleNamespace(player_id=1, name='A'), base, removed, 6)
    assert row['win_delta'] == pytest.approx(.4)
    assert row['category_deltas'] == pytest.approx({'PTS': .3, 'FT%': -.1})
