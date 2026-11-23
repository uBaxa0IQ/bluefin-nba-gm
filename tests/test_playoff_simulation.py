from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from core.monte_carlo import WeekPlan, simulate_seasons
from core.playoff import playoff_scoring_calendar
from core.playoff_simulation import PlayoffRound, Postseason, simulate_playoffs
from web.backend.services.monte_carlo import load_inputs, save_inputs


def test_all_star_break_extends_semifinal_and_final_ends_on_espn_last_day():
    start = datetime(2026, 10, 20, 23, tzinfo=timezone.utc)
    schedule = {str(day): [{'date': int((start + timedelta(days=day-1)).timestamp() * 1000)}]
                for day in range(1, 147) if day not in range(122, 129)}
    settings = SimpleNamespace(reg_season_count=16,
        matchup_periods={str(i): [i] for i in range(1, 19)} | {'19': [19, 20]})
    league = SimpleNamespace(settings=settings, firstScoringPeriod=1, finalScoringPeriod=146,
                             pro_schedule={1: schedule})
    calendar = playoff_scoring_calendar(league)
    assert {week: (len(days), a, b) for week, (days, a, b) in calendar.items()} == {
        17: (7, '2027-02-08', '2027-02-14'),
        18: (14, '2027-02-15', '2027-02-28'),
        19: (14, '2027-03-01', '2027-03-14'),
    }
    assert calendar[19][0][-1] == 146


def _teams():
    return [{'team_id': i, 'team_name': str(i), 'wins': 0, 'losses': 0, 'ties': 0} for i in range(1, 15)]


def _rounds():
    return tuple(PlayoffRound(WeekPlan(i, {}, ()), f'2027-03-0{i}', f'2027-03-0{i+1}') for i in range(1, 4))


def test_regular_season_and_playoff_paths_share_the_same_drawn_seed():
    result = simulate_seasons(_teams(), [], {}, categories=['PTS'], trials=500, postseason=Postseason(_rounds()))
    post = result['postseason']
    for row in post['teams']:
        original = next(t for t in result['standings'] if t['team_id'] == row['team_id'])
        assert row['p_playoffs'] == pytest.approx(original['p_playoffs'])
        assert row['p_title'] == pytest.approx(original['rank_probabilities']['1'])
        assert row['p_title'] <= row['p_final'] <= row['p_semifinal'] <= row['p_playoffs']
        assert sum(row['finish_probabilities'].values()) == pytest.approx(1)
    assert sum(t['p_title'] for t in post['teams']) == pytest.approx(1)
    assert sum(t['p_final'] for t in post['teams']) == pytest.approx(2)


def test_category_odds_only_include_trials_where_the_teams_meet():
    ids = list(range(1, 15))
    order = list(range(14))
    alternate = order.copy()
    alternate[6], alternate[7] = alternate[7], alternate[6]
    first, second, third = _rounds()
    first = replace(first, plan=WeekPlan(1, {}, (), actual={
        1: {'PTS': 10, 'REB': 3, 'TO': 1},
        8: {'PTS': 20, 'REB': 3, 'TO': 2},
        7: {'PTS': 5, 'REB': 3, 'TO': 1},
    }))
    post = simulate_playoffs(ids, np.array([order, alternate]), Postseason((first, second, third)),
                             {}, ['PTS', 'REB', 'TO'], ['TO'], 42)
    pairs = {(m['team_id'], m['opponent_id']): m for m in post['rounds'][0]['matchups']}
    one_eight = pairs[1, 8]
    assert one_eight['p_meet'] == .5
    assert one_eight['samples'] == 1
    assert one_eight['categories'] == {
        'PTS': {'p_win': 0, 'p_tie': 0, 'p_loss': 1},
        'REB': {'p_win': 0, 'p_tie': 1, 'p_loss': 0},
        'TO': {'p_win': 1, 'p_tie': 0, 'p_loss': 0},
    }
    assert pairs[8, 1]['categories']['TO']['p_loss'] == 1
    assert pairs[1, 7]['categories']['PTS']['p_win'] == 1


def test_official_upset_advances_and_eliminated_teams_play_for_places(tmp_path):
    first, second, third = _rounds()
    first = replace(first, official=(('championship', 1, 8, 8), ('championship', 4, 5, 4),
        ('championship', 3, 6, 6), ('championship', 2, 7, 2),
        ('consolation', 9, 10, 10), ('consolation', 11, 12, 11), ('consolation', 13, 14, 13)),
        official_stats={1: {'PTS': 10}, 8: {'PTS': 20}})
    plan = Postseason((first, second, third), tuple(range(1, 15)))
    path = tmp_path / 'playoffs.json'
    save_inputs(path, {'weeks': [], 'postseason': plan}, {}, [])
    assert load_inputs(path)[0]['postseason'] == plan
    post = simulate_seasons(_teams(), [], {}, categories=['PTS'], trials=20, postseason=plan)['postseason']
    pairs = {(m['team_id'], m['opponent_id']): m for m in post['rounds'][0]['matchups']}
    assert pairs[8, 1]['official']
    assert pairs[8, 1]['categories']['PTS']['p_win'] == 1
    assert pairs[4, 5]['categories'] == {}
    second = post['rounds'][1]['matchups']
    assert {(m['team_id'], m['opponent_id']) for m in second if m['team_id'] < m['opponent_id']} == {
        (4, 8), (2, 6), (1, 3), (5, 7), (10, 11), (9, 13), (12, 14),
    }
    by_id = {t['team_id']: t for t in post['teams']}
    assert by_id[8]['p_semifinal'] == 1
    assert by_id[1]['p_title'] == 0
    assert by_id[2]['p_title'] == 1
    assert by_id[9]['p_title_given_playoffs'] is None
