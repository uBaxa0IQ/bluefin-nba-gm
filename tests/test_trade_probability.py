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


def test_category_probabilities_average_official_matches_from_each_side():
    def match(a, b, win, loss, official=True):
        return dict(team1_id=a, team2_id=b, official=official,
                    categories={'PTS': {'p_win': win, 'p_tie': 1-win-loss, 'p_loss': loss}})
    forecast = {'categories': ['PTS'], 'standings': [{'team_id': i} for i in (1, 2, 3)],
        'weeks': [{'matchups': [match(1, 2, .7, .2), match(1, 3, 1, 0, False)]},
                  {'matchups': [match(2, 1, .4, .5)]}]}
    values = {t['team_id']: t['category_probabilities']['PTS'] for t in service.category_probabilities(forecast)}
    assert values[1] == pytest.approx(.6)
    assert values[2] == pytest.approx(.3)
    assert values[3] is None


def test_trade_matchups_keep_official_weeks_and_championship_pairs():
    forecast = {
        'weeks': [{'week': 6, 'matchups': [
            dict(team1_id=1, team2_id=2, official=True, p_win=.7, p_loss=.2),
            dict(team1_id=1, team2_id=3, official=False, p_win=.9, p_loss=.1),
        ]}],
        'postseason': {
            'teams': [dict(team_id=1, p_final=.3, p_title=.2)],
            'rounds': [{'week': 17, 'start': '2027-02-08', 'end': '2027-02-14', 'matchups': [
                dict(team_id=1, opponent_id=2, bracket='championship', p_meet=.3, p_win=.6),
                dict(team_id=1, opponent_id=3, bracket='consolation', p_meet=.2, p_win=.5),
            ]}],
        },
    }
    a, b, c = service.trade_matchup_probabilities(forecast, [{'team_id': i} for i in (1, 2, 3)])
    assert a['p_title'] == .2
    assert a['regular_matchups'] == [dict(week=6, opponent_id=2, p_win=.7)]
    assert b['regular_matchups'] == [dict(week=6, opponent_id=1, p_win=.2)]
    assert c['regular_matchups'] == []
    assert a['playoff_matchups'][0]['opponents'] == [dict(opponent_id=2, p_meet=.3, p_win=.6)]
