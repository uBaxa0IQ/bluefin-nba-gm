from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace

from core.projection import build_matchup_lineups
from core.roster_timeline import InjuryContext
from core.snapshot import LeagueSnapshot, PlayerSnapshot
from web.backend.services.monte_carlo import prepare_season
from web.backend.services import projections


def player(pid, name, *, team=1, slot='BE', z=1, days=(1, 2, 3), droppable=True):
    return PlayerSnapshot(
        pid, name, team, f'Team {team}', 'PG', ('PG',), slot, False, 'ACTIVE',
        None, {str(day): {'date': datetime(2026, 12, day, 23, tzinfo=timezone.utc)} for day in days},
        {'PTS': 10}, {'PTS': z}, droppable=droppable,
    )


def out(pid, until=None, *, season=False):
    return {'player_id': pid, 'injury_status': 'OUT', 'expected_return_date': until,
            'out_for_season': season}


def test_return_activates_ir_and_drops_only_an_eligible_player():
    roster = [
        player(1, 'IR return', slot='IR', z=6),
        player(2, 'Temporary player', z=-3),
        player(3, 'Protected player', z=-9, days=(3,), droppable=False),
        player(4, 'Regular return', z=4),
        player(5, 'No return date', slot='IR', z=8),
        player(6, 'Out for season', slot='IR', z=10),
        player(7, 'Past estimated date', slot='IR', z=11),
    ]
    report = [out(1, '2026-12-02'), out(4, '2026-12-03'), out(5),
              out(6, '2026-12-02', season=True), out(7, '2026-11-30')]
    context = InjuryContext(date(2026, 12, 1), 3, {r['player_id']: r for r in report})
    planned, details = context.plan([p.as_projection_player() for p in roster])

    assert [(e['kind'], e.get('dropped')) for e in details['events']] == [
        ('activate_ir', 'Temporary player'), ('return', None),
    ]
    assert [r['player_id'] for r in details['unavailable']] == [5, 6, 7]
    days = build_matchup_lineups(planned, [1, 2, 3], ('PG', 'UT', 'UT'))['days']
    assert [{s['player']['name'] for s in day['starters']} for day in days] == [
        {'Temporary player'}, {'IR return'}, {'IR return', 'Protected player', 'Regular return'},
    ]
    assert all(not p.as_projection_player().get('available_until') for p in roster)


def test_ir_drop_uses_punts_only_for_the_configured_team():
    returning = player(1, 'Returns', slot='IR')
    big = replace(player(2, 'Big'), z_scores={'PTS': -9, 'REB': 4})
    scorer = replace(player(3, 'Scorer'), z_scores={'PTS': 4, 'REB': -1})
    roster = [p.as_projection_player() for p in (returning, big, scorer)]
    report = {1: out(1, '2026-12-02')}
    context = InjuryContext(date(2026, 12, 1), 2, report,
                            punt_team_id=1, punt_categories=frozenset({'PTS'}))

    assert context.plan(roster, 1)[1]['events'][0]['dropped'] == 'Scorer'
    assert context.plan(roster, 2)[1]['events'][0]['dropped'] == 'Big'
    assert replace(context, punt_categories=frozenset()).plan(roster, 1)[1]['events'][0]['dropped'] == 'Big'


def test_ir_return_keeps_existing_player_when_worse_under_team_punts():
    returning = replace(player(1, 'Returning shooter', slot='IR'), z_scores={'PTS': 5, 'REB': -3})
    incumbent = replace(player(2, 'Incumbent'), z_scores={'PTS': -1, 'REB': -1})
    roster = [p.as_projection_player() for p in (returning, incumbent)]
    context = InjuryContext(date(2026, 12, 1), 1, {1: out(1, '2026-12-02')},
                            punt_team_id=1, punt_categories=frozenset({'PTS'}))

    planned, details = context.plan(roster, 1)
    assert details['events'] == [{'date': '2026-12-02', 'kind': 'activation_blocked',
                                  'player': 'Returning shooter'}]
    assert not planned[0]['available']
    assert 'available_until' not in planned[1]
    assert context.plan(roster, 2)[1]['events'][0]['dropped'] == 'Incumbent'


def test_planned_ir_drops_use_the_roster_at_each_return():
    roster = [player(1, 'Mara', slot='IR', z=5), player(2, 'Chet', slot='IR', z=1),
              player(3, 'Donte', slot='IR', z=8), player(4, 'Goodwin', z=2), player(5, 'Other', z=-2)]
    report = {i: out(i, f'2026-12-0{i + 1}') for i in (1, 2, 3)}
    context = InjuryContext(date(2026, 12, 1), 2, report, ir_return_drops={1: 4, 2: 1, 3: 3})
    planned, details = context.plan([p.as_projection_player() for p in roster], 1, include_return_steps=True)
    assert [(e['kind'], e['player'], e['dropped']) for e in details['events']] == [
        ('activate_ir', 'Mara', 'Goodwin'), ('activate_ir', 'Chet', 'Mara'), ('drop_on_return', 'Donte', 'Donte'),
    ]
    assert [{p['name'] for p in s['candidates']} for s in details['return_steps']] == [
        {'Goodwin', 'Other'}, {'Mara', 'Other'}, {'Chet', 'Other'},
    ]
    assert details['return_steps'][0]['automatic_drop'] == 'Other'
    assert planned[0]['available_from'] == date(2026, 12, 2)
    assert planned[0]['available_until'] == date(2026, 12, 3)
    assert not planned[2]['available']
    assert 'available_until' not in planned[4]


def test_monte_carlo_and_week_projection_share_the_dated_roster(monkeypatch):
    teams = [SimpleNamespace(team_id=i, team_name=f'Team {i}', wins=0, losses=0, ties=0) for i in (1, 2)]
    snapshot = LeagueSnapshot(
        '2027_total', datetime(2026, 12, 1, 12, tzinfo=timezone.utc), 1, 1,
        (player(1, 'IR return', slot='IR', z=6), player(2, 'Temporary player'),
         player(3, 'Opponent', team=2)), {}, ('UT',),
    )
    league = SimpleNamespace(
        currentMatchupPeriod=1, scoringPeriodId=1,
        settings=SimpleNamespace(reg_season_count=2, playoff_team_count=1,
                                 matchup_periods={1: [1, 2], 2: [3]},
                                 position_slot_counts={'UT': 1}),
    )
    raw = {'settings': {'scheduleSettings': {}}, 'schedule': [
        {'matchupPeriodId': week, 'home': {'teamId': 1}, 'away': {'teamId': 2}} for week in (1, 2)
    ]}
    metadata = SimpleNamespace(
        league=league, league_data=raw, league_id=1, year=2027, reverse_categories=set(),
        scoring_type='H2H_MOST_CATEGORIES', get_categories=lambda: ['PTS'],
        projection_injuries={'players': [out(1, '2026-12-02')]},
        get_teams=lambda: teams, get_team_by_id=lambda team: teams[team - 1],
        get_matchup_box_score=lambda *_: None,
    )
    # Keep both paths at the same snapshot instant, independent of the test run date.
    monkeypatch.setattr(projections, 'build_league_snapshot', lambda *args, **kwargs: snapshot)
    monkeypatch.setattr(projections, 'get_matchup_scoring_periods', lambda _, week: [3] if week == 2 else [1, 2])
    prepared = prepare_season(metadata, snapshot.period, snapshot=snapshot, simulation_mode='injury_aware')
    assert prepared['weeks'][0].games[1] == {2: 1, 1: 1}
    assert prepared['weeks'][1].games[1] == {1: 1}
    week_two = projections.project_team_matchup(metadata, 1, snapshot.period, 2, simulation_mode='injury_aware')
    assert week_two['selected_games'] == {'IR return': 1, 'Temporary player': 0}
    assert week_two['roster_timeline']['events'] == prepared['metadata']['roster_timelines']['1']['events']
