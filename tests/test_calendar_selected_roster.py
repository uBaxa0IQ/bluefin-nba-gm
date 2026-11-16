from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core.snapshot import LeagueSnapshot, PlayerSnapshot
from web.backend.services import projections


@pytest.fixture
def calendar_league(monkeypatch):
    now = datetime.now(timezone.utc)

    def player(name, slot, value, injured=False):
        return PlayerSnapshot(
            player_id=None, name=name, fantasy_team_id=1, fantasy_team_name='Team',
            position='PG', eligible_slots=('PG', 'UT'), lineup_slot=slot,
            injured=injured, injury_status='OUT' if injured else 'ACTIVE', pro_team=None,
            schedule={'1': {'date': now + timedelta(days=1)}}, stats={'PTS': value},
            z_scores={'PTS': value}, expected_return_date=now + timedelta(days=30),
        )

    players = (player('OUT', 'BE', 10, True), player('IR', 'IR', 20, True), player('Healthy', 'PG', 30))
    snapshot = LeagueSnapshot('2027_total', now, 1, 1, players, {}, ('UT', 'UT', 'UT'))
    team = SimpleNamespace(team_id=1, team_name='Team')
    metadata = SimpleNamespace(
        league=SimpleNamespace(currentMatchupPeriod=1),
        get_team_by_id=lambda _: team, get_teams=lambda: [team],
        get_matchup_box_score=lambda *args: None,
    )
    monkeypatch.setattr(projections, 'build_league_snapshot', lambda *args: snapshot)
    monkeypatch.setattr(projections, 'get_matchup_scoring_periods', lambda *args: [1])
    monkeypatch.setattr(projections, 'get_remaining_scoring_periods', lambda *args: [1])
    return metadata, snapshot, team


@pytest.mark.parametrize(('mode', 'names', 'expected'), [
    ('all', (), {'OUT': 1, 'IR': 1, 'Healthy': 1}),
    ('exclude_ir', (), {'OUT': 1, 'Healthy': 1}),
    ('top_n', ('OUT', 'IR'), {'OUT': 1, 'IR': 1}),
    ('top_n', (), {'IR': 1, 'Healthy': 1}),
])
def test_calendar_team_and_league_use_selected_roster_despite_injuries(calendar_league, mode, names, expected):
    metadata, snapshot, team = calendar_league
    result = projections.project_team_matchup(
        metadata, 1, '2027_total', remaining_only=True,
        simulation_mode=mode, top_n_players=2, custom_team_players=names,
    )
    assert result['selected_games'] == expected
    _, league_lineups = projections.project_snapshot_for_matchup(
        snapshot, [team], [1], simulation_mode=mode, top_n_players=2,
        custom_team_id=1, custom_team_players=names,
    )
    assert league_lineups[1]['selected_games'] == expected


def test_calendar_roster_selection_does_not_override_source_data():
    player = {'name': 'OUT', 'available': False, 'injured': True, 'injury_status': 'OUT'}
    selected = projections.select_projection_roster([player], 'top_n', 13, ('OUT',))
    assert selected[0]['available'] is True
    assert player['available'] is False


def test_lineup_api_passes_manual_selection_to_calendar(calendar_league, monkeypatch):
    from routers import lineup

    metadata, _, _ = calendar_league
    monkeypatch.setattr(lineup, 'project_team_matchup', projections.project_team_matchup)
    response = lineup.optimize_team_lineup(
        1, period='2027_total', simulation_mode='top_n', custom_team_players='OUT,IR',
        league_meta=metadata,
    )
    assert response['selected_games'] == {'OUT': 1, 'IR': 1}


@pytest.mark.parametrize(('mode', 'names'), [('exclude_ir', ()), ('top_n', ('OUT', 'IR'))])
def test_game_counts_follow_roster_mode_and_ignore_injuries(calendar_league, monkeypatch, mode, names):
    from web.backend.services import game_usage
    metadata, snapshot, team = calendar_league
    team.roster = [SimpleNamespace(
        name=player.name, playerId=player.name, position=player.position,
        eligibleSlots=player.eligible_slots, lineupSlot=player.lineup_slot,
        injured=player.injured, injuryStatus=player.injury_status, schedule=player.schedule,
    ) for player in snapshot.players]
    metadata.league.scoringPeriodId = 0
    monkeypatch.setattr(game_usage, 'build_league_snapshot', lambda *args: snapshot)
    monkeypatch.setattr(game_usage, 'get_matchup_scoring_periods', lambda *args: [1])
    monkeypatch.setattr(game_usage, 'league_slots', lambda *args: snapshot.active_slots)
    result = game_usage.get_week_game_usage(
        metadata, (1,), period='2027_total', simulation_mode=mode,
        custom_team_id=1, custom_team_players=names,
    )
    assert result[1] == {'played': 0, 'projected_total': 2}


@pytest.mark.parametrize(('mode', 'names'), [('exclude_ir', {'OUT', 'Healthy'}), ('top_n', {'OUT', 'IR'})])
def test_trade_calendar_keeps_selected_injured_players(calendar_league, monkeypatch, mode, names):
    from web.backend.services import trades
    metadata, snapshot, _ = calendar_league
    monkeypatch.setattr(trades, 'build_league_snapshot', lambda *args: snapshot)
    monkeypatch.setattr(trades, 'get_remaining_scoring_periods', lambda *args: [1])
    before = after = {1: names} if mode == 'top_n' else None
    result = trades.analyze_calendar_trade(
        metadata, '2027_total', {1: {'give': [], 'receive': []}},
        selected_before=before, selected_after=after, simulation_mode=mode,
    )
    assert result['teams'][1]['selected_games_before'] == 2
    assert result['teams'][1]['selected_games_after'] == 2


def test_free_agent_baseline_uses_manual_roster(calendar_league, monkeypatch):
    from web.backend.services import waivers
    metadata, snapshot, _ = calendar_league
    metadata.year = 2027
    metadata.get_free_agents = lambda **kwargs: []
    metadata.get_all_players_stats = lambda *args: []
    monkeypatch.setattr(waivers, 'build_league_snapshot', lambda *args: snapshot)
    monkeypatch.setattr(waivers, 'get_remaining_scoring_periods', lambda *args: [1])
    original = waivers._lineup_projection
    rosters = []

    def capture(players, *args):
        rosters.append({player['name'] for player in players})
        return original(players, *args)

    monkeypatch.setattr(waivers, '_lineup_projection', capture)
    result = waivers.recommend_free_agents(
        metadata, 1, '2027_total', simulation_mode='top_n', custom_team_players=('OUT', 'IR'),
    )
    assert rosters == [{'OUT', 'IR'}]
    assert result['baseline_selected_games'] == 2


def test_removed_odds_endpoint_is_not_registered():
    from web.backend.main import app
    assert '/api/matchup/odds' not in {route.path for route in app.routes}
