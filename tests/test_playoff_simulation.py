from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core.monte_carlo import WeekPlan, simulate_seasons
from core.playoff import playoff_scoring_calendar
from core.playoff_simulation import PlayoffRound, Postseason
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


def test_official_upset_advances_and_eliminated_teams_play_for_places(tmp_path):
    first, second, third = _rounds()
    first = replace(first, official=(('championship', 1, 8, 8), ('championship', 4, 5, 4),
        ('championship', 3, 6, 6), ('championship', 2, 7, 2),
        ('consolation', 9, 10, 10), ('consolation', 11, 12, 11), ('consolation', 13, 14, 13)))
    plan = Postseason((first, second, third), tuple(range(1, 15)))
    path = tmp_path / 'playoffs.json'
    save_inputs(path, {'weeks': [], 'postseason': plan}, {}, [])
    assert load_inputs(path)[0]['postseason'] == plan
    post = simulate_seasons(_teams(), [], {}, categories=['PTS'], trials=20, postseason=plan)['postseason']
    second = post['rounds'][1]['matchups']
    assert {(m['team_id'], m['opponent_id']) for m in second if m['team_id'] < m['opponent_id']} == {
        (4, 8), (2, 6), (1, 3), (5, 7), (10, 11), (9, 13), (12, 14),
    }
    by_id = {t['team_id']: t for t in post['teams']}
    assert by_id[8]['p_semifinal'] == 1
    assert by_id[1]['p_title'] == 0
    assert by_id[2]['p_title'] == 1
    assert by_id[9]['p_title_given_playoffs'] is None
