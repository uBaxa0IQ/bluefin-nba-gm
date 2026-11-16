from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.snapshot import PlayerSnapshot, LeagueSnapshot
from web.backend.services import trade_probability as service


def player(name, team):
    return PlayerSnapshot(player_id=team, name=name, fantasy_team_id=team,
        fantasy_team_name=str(team), position='PG', eligible_slots=('PG',), lineup_slot='PG',
        injured=False, injury_status='ACTIVE', pro_team='BOS', schedule={}, stats={}, z_scores={})


@pytest.fixture
def inputs(monkeypatch):
    snapshot = LeagueSnapshot('test', datetime.now(timezone.utc), 5, 30,
        (player('A', 1), player('B', 2)), {})
    monkeypatch.setattr(service, 'build_league_snapshot', lambda *args: snapshot)
    meta = SimpleNamespace(get_teams=lambda: [SimpleNamespace(team_id=i, team_name=str(i)) for i in (1, 2)])
    params = dict(period='test', my_team_id=1, their_team_id=2, i_give=['A'], i_receive=['B'],
        custom_rosters={1: ['A'], 2: ['B']}, top_n_players=13, punt_categories=[])
    return meta, params


def test_trade_moves_ownership_and_manual_selection_without_mutating_original(inputs):
    before, after, custom = service.trade_snapshots(*inputs)
    assert [p.name for p in before.team_players(1)] == ['A']
    assert [p.name for p in after.team_players(1)] == ['B']
    assert [p.name for p in after.team_players(2)] == ['A']
    assert custom == {1: ['B'], 2: ['A']}
    assert inputs[1]['custom_rosters'] == {1: ['A'], 2: ['B']}


@pytest.mark.parametrize('changes', [dict(their_team_id=1), dict(i_give=['B']),
    dict(i_receive=['A']), dict(i_give=['A', 'A']), dict(custom_rosters={99: ['A']})])
def test_invalid_trade_is_rejected(inputs, changes):
    meta, params = inputs
    with pytest.raises(ValueError):
        service.trade_snapshots(meta, {**params, **changes})
