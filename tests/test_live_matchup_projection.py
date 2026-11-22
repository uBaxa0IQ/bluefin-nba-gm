from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest
from espn_api.basketball.constant import STATS_MAP

from core.live_games import LIVE_COMPONENTS, LiveGame, expected_remainder
from core.matchup_value import combine_stats
from core.monte_carlo import INDEX, PlayerDistribution, sample_remainder, simulate_seasons
from core.snapshot import LeagueSnapshot, PlayerSnapshot
from web.backend.services.live_matchups import _live_box, _parse_matchup
from web.backend.services.monte_carlo import load_inputs, prepare_season, save_inputs
from web.backend.services.projections import project_snapshot_for_matchup
from web.backend.services.roster_contribution import without_player


CODES = {name: code for code, name in STATS_MAP.items()}
GAME = 123456
DAY = 1
PLAYED = {'MIN': 20, 'PTS': 9, 'FGM': 4, 'FGA': 10, '3PM': 1, '3PA': 4, 'REB': 10}
AVERAGE = {'MIN': 36, 'PTS': 18, 'FGM': 7, 'FGA': 12, '3PM': 3, '3PA': 5, 'FTM': 1, 'FTA': 2, 'AST': 6}


def lineup_entry(player_id, position, stats, split_id, day):
    return {'playerId': player_id, 'lineupSlotId': position, 'playerPoolEntry': {'player': {
        'id': player_id, 'proTeamId': 10, 'stats': [
            {'id': split_id, 'scoringPeriodId': day, 'stats': {CODES[k]: v for k, v in stats.items()}}
        ],
    }}}


def live_data(now, *, state='in', nba_pts=9):
    labels = ['MIN', 'PTS', 'FG', '3PT', 'FT', 'REB', 'AST', 'TO', 'STL', 'BLK']
    summary = {
        'header': {'competitions': [{'status': {'type': {'state': state}, 'period': 3, 'displayClock': '4:00'}}]},
        'boxscore': {'players': [{'statistics': [{'labels': labels, 'athletes': [
            {'athlete': {'id': str(i)}, 'stats': ['20', str(nba_pts), '4-10', '1-4', '0-0', '10', '0', '0', '0', '0']}
            for i in (11, 12)
        ]}]}]},
    }
    settled = {k: 0 for k in LIVE_COMPONENTS}
    credited = {**settled, **PLAYED}
    side = {'teamId': 1,
            'cumulativeScore': {'scoreByStat': {CODES[k]: {'score': v} for k, v in settled.items()}},
            'cumulativeScoreLive': {'scoreByStat': {CODES[k]: {'score': v} for k, v in credited.items()}},
            'rosterForMatchupPeriod': {'entries': [lineup_entry(11, 0, credited, '05null', 0)]},
            'rosterForMatchupPeriodDelayed': {'entries': []},
            'rosterForCurrentScoringPeriod': {'entries': [
                lineup_entry(11, 0, PLAYED, f'05{GAME}', DAY),
                lineup_entry(12, 12, PLAYED, f'05{GAME}', DAY),
            ]}}
    raw = {'schedule': [{'matchupPeriodId': 1, 'home': side, 'away': {'teamId': 2}}]}
    return _parse_matchup(raw, 1, DAY, now, {10: [{'id': GAME}]}, {GAME: _live_box(summary)}, ('PG',))


def test_calendar_and_simulation_share_credits_and_do_not_reuse_locked_slot(tmp_path):
    now = datetime.now(timezone.utc)
    current = live_data(now)

    def player(pid, date, stats):
        return PlayerSnapshot(pid, str(pid), 1, 'One', 'PG', ('PG',), 'PG', False, 'ACTIVE',
                              None, {str(DAY): {'date': date}}, stats, {'PTS': 1})

    # Swap the live player on paper. His current game still belongs to the
    # team that locked him, even while projecting the incoming player's schedule.
    live = replace(player(11, now - timedelta(hours=1), AVERAGE), fantasy_team_id=2)
    incoming = player(21, now + timedelta(hours=1), {'PTS': 100})
    snapshot = LeagueSnapshot('test', now, 1, DAY, (live, incoming), {}, ('PG',))
    teams = [SimpleNamespace(team_id=i, team_name=str(i), wins=0, losses=0, ties=0) for i in (1, 2)]

    team_stats, lineups = project_snapshot_for_matchup(snapshot, teams, [DAY], future_only=True, current=current)
    projected = combine_stats(current.actual[1], team_stats[1]['stats'])
    assert lineups[1]['selected_games'] == {'21': 0}
    assert team_stats[2]['stats']['PTS'] == 0
    assert projected['PTS'] == 17
    assert projected['AST'] == pytest.approx(6 * 16 / 36)
    assert projected['FG%'] == pytest.approx((4 + 7 * 16 / 36) / (10 + 12 * 16 / 36))
    assert 0 < projected['DD'] < 1

    league = SimpleNamespace(currentMatchupPeriod=1, scoringPeriodId=DAY,
        settings=SimpleNamespace(matchup_periods={'1': [DAY]}, reg_season_count=1, playoff_team_count=1))
    metadata = SimpleNamespace(league=league, league_id=1, year=2027, scoring_type='H2H_MOST_CATEGORIES',
        reverse_categories=set(), get_teams=lambda: teams, get_categories=lambda: ['PTS'],
        league_data={'settings': {'scheduleSettings': {}}, 'schedule': [
            {'matchupPeriodId': 1, 'home': {'teamId': 1}, 'away': {'teamId': 2}}
        ]})
    prepared = prepare_season(metadata, 'test', snapshot=snapshot, live_matchup=current)
    week = prepared['weeks'][0]
    assert week.games == {1: {}, 2: {}}
    assert set(week.live_games[1]) == {11} and not week.live_games[2]
    assert week.actual[1]['PTS'] == 9
    distributions = {11: PlayerDistribution([[AVERAGE.get(k, 0) for k in INDEX]], [1])}
    removed = without_player([week], 1, 11)[0]
    assert removed.actual == week.actual
    assert not removed.live_games[1]
    opposition = {**week.actual, 2: {'PTS': 12}}
    baseline = simulate_seasons(prepared['teams'], [replace(week, actual=opposition)], distributions,
                                categories=['PTS'], trials=1_000, playoff_teams=1)
    assert .8 < baseline['weeks'][0]['matchups'][0]['p_win'] < 1
    path = tmp_path / 'inputs.json'
    save_inputs(path, prepared, distributions, [])
    restored, _ = load_inputs(path)
    assert restored['weeks'] == [week]


@pytest.mark.parametrize(('state', 'points'), [('post', 9), ('in', 10)])
def test_final_or_out_of_sync_games_keep_credits_without_a_forecast(state, points):
    current = live_data(datetime.now(timezone.utc), state=state, nba_pts=points)
    assert current.actual[1]['PTS'] == 9
    assert current.open_slots(1, ('PG',)) == ()
    assert current.confirmed[1] == {}


def test_remainder_samples_have_consistent_shots_and_award_dd_once():
    distribution = PlayerDistribution([[AVERAGE.get(k, 0) for k in INDEX]], [1])
    game = LiveGame(.4, PLAYED)
    rows = sample_remainder(distribution, game, 1_000, np.random.default_rng(1))
    np.testing.assert_array_equal(rows[:, INDEX['PTS']], rows[:, INDEX['FGM']] * 2
                                  + rows[:, INDEX['3PM']] + rows[:, INDEX['FTM']])
    assert np.all(rows[:, INDEX['FGM']] <= rows[:, INDEX['FGA']])
    assert np.all(rows[:, INDEX['3PM']] <= rows[:, INDEX['3PA']])
    assert np.all(rows[:, INDEX['FTM']] <= rows[:, INDEX['FTA']])
    np.testing.assert_array_equal(rows[:, INDEX['DD']], rows[:, INDEX['PTS']] > 0)
    credited_dd = LiveGame(.4, {**PLAYED, 'PTS': 10, 'DD': 1})
    assert expected_remainder(AVERAGE, credited_dd)['DD'] == 0
    assert not np.any(sample_remainder(distribution, credited_dd, 100, np.random.default_rng(1))[:, INDEX['DD']])
