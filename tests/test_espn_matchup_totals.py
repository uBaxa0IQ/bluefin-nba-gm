from pathlib import Path
from types import SimpleNamespace

from espn_api.basketball.constant import STATS_MAP

from core.league_metadata import LeagueMetadata


def test_matchup_totals_follow_espn_scoreboard_not_raw_player_stats():
    home = SimpleNamespace(team_id=1, team_name='Home')
    away = SimpleNamespace(team_id=2, team_name='Away')
    player = SimpleNamespace(
        name='Player', playerId=42, position='PG', slot_position='BE',
        stats={'0': {'total': {'PTS': 91, 'FGM': 40, 'FGA': 80}}},
    )
    box = SimpleNamespace(
        home_team=home, away_team=away, home_lineup=[player], away_lineup=[],
        home_stats={'PTS': {'value': 0, 'result': 'TIE'},
                    'FGM': {'value': 0}, 'FGA': {'value': 0},
                    'FG%': {'value': 0}},
        away_stats={'PTS': {'value': 0}},
    )
    metadata = LeagueMetadata()
    metadata.league = SimpleNamespace()
    metadata.teams = [home, away]
    metadata._get_box_scores_cached = lambda week: [box]

    current = metadata.get_matchup_box_score(1, 1)
    assert current['totals']['PTS'] == 0
    assert current['totals']['FGM'] == 0
    assert metadata.get_all_teams_stats_for_week(1)[1]['stats']['PTS'] == 0

    box.home_stats['PTS']['value'] = 55
    box.home_stats['FGM']['value'] = 20
    box.home_stats['FGA']['value'] = 40
    box.home_stats['FG%']['value'] = 0.5
    updated = metadata.get_matchup_box_score(1, 1)
    assert updated['totals']['PTS'] == 55
    assert updated['totals']['FGM'] == 20
    assert updated['totals']['FGA'] == 40
    assert updated['totals']['FG%'] == 0.5


def test_matchup_details_keep_zero_stats_and_use_the_opponents_live_totals(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'web' / 'backend'))
    from routers.dashboard import get_matchup_details
    from services import live_matchups

    home = SimpleNamespace(team_id=1, team_name='Home')
    away = SimpleNamespace(team_id=2, team_name='Away')
    box = SimpleNamespace(home_team=home, away_team=away, home_lineup=[], away_lineup=[],
                          home_stats={'PTS': {'value': 0}}, away_stats={'PTS': {'value': 0}})
    metadata = LeagueMetadata()
    metadata.league = SimpleNamespace(currentMatchupPeriod=1, scoringPeriodId=1)
    metadata.teams = [home, away]
    metadata._get_box_scores_cached = lambda week: [box]
    points_code = next(code for code, name in STATS_MAP.items() if name == 'PTS')
    live_points = {'score': 0}
    scoreboard = {'schedule': [{
        'matchupPeriodId': 1, 'winner': 'UNDECIDED', 'home': {'teamId': 1},
        'away': {'teamId': 2, 'cumulativeScoreLive': {'scoreByStat': {points_code: live_points}}},
    }]}
    monkeypatch.setattr(live_matchups, 'read_fantasy_day', lambda *args: scoreboard)

    details = get_matchup_details(1, 1, league_meta=metadata, include_game_usage=False)
    assert details['opponent']['id'] == 2
    assert details['score'] == f"0-0-{len(details['categories'])}"
    assert all(row['my_value'] == row['opponent_value'] == 0 for row in details['categories'])

    box.away_stats['PTS']['value'] = 6
    live_points['score'] = 12
    details = get_matchup_details(1, 1, league_meta=metadata, include_game_usage=False)
    points = next(row for row in details['categories'] if row['category'] == 'PTS')
    assert points == {'category': 'PTS', 'my_value': 0, 'opponent_value': 12, 'winner': 'opponent'}
    assert details['score'] == f"0-1-{len(details['categories']) - 1}"

    metadata.league.currentMatchupPeriod = 2
    historical = get_matchup_details(1, 1, league_meta=metadata, include_game_usage=False)
    assert next(row['opponent_value'] for row in historical['categories'] if row['category'] == 'PTS') == 6
