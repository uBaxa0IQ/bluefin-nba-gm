from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from espn_api.basketball.constant import STATS_MAP

from core.monte_carlo import COMPONENTS, PlayerDistribution
from web.backend.services import matchup_timeline as timeline


CODES = {name: key for key, name in STATS_MAP.items()}
START = datetime(2026, 11, 1, 22, tzinfo=timezone.utc)


def entry(player_id, pro_team, slot, gid, points):
    stat = {CODES['PTS']: points, CODES['GP']: 1}
    return {'lineupSlotId': slot, 'playerPoolEntry': {'player': {
        'id': player_id, 'fullName': f'Player {player_id}', 'proTeamId': pro_team, 'eligibleSlots': [0, 11],
        'stats': [{'id': f'05{gid}', 'scoringPeriodId': 1, 'stats': stat}],
    }}}


def setup(monkeypatch, *, partial=False):
    # Game 102 starts later but reaches its final whistle first.
    game = lambda gid, tipoff: {'id': gid, 'date': int(tipoff.timestamp() * 1000), 'validForLocking': True}
    league = SimpleNamespace(currentMatchupPeriod=1 if partial else 2, scoringPeriodId=1 if partial else 2,
        settings=SimpleNamespace(position_slot_counts={'0': 1}, matchup_periods={'1': [1]}),
        pro_schedule={1: {'1': [game(101, START)]}, 2: {'1': [game(102, START + timedelta(hours=1))]}})
    match = {'matchupPeriodId': 1, 'winner': 'UNDECIDED' if partial else 'AWAY',
             'home': {'teamId': 1, 'rosterForCurrentScoringPeriod': {'entries': [
                 entry(11, 1, 0, 101, 1), entry(12, 2, 12, 102, 999),
             ]}},
             'away': {'teamId': 2, 'rosterForCurrentScoringPeriod': {'entries': [entry(21, 2, 0, 102, 10)]}}}
    meta = SimpleNamespace(league=league, year=2027, scoring_type='H2H_MOST_CATEGORIES', reverse_categories=set(),
        get_categories=lambda: ['PTS'], league_data={'schedule': [match]})

    def finished(gid, cache_bucket):
        points = {11: {'PTS': 1}} if gid == 101 else {21: {'PTS': 11 if partial else 10}}
        return timeline.FinalGame(START + timedelta(hours=4 if gid == 101 else 3), str(gid), points)

    def histories(players, year, cache_dir, *, as_of, historical):
        assert as_of < START
        assert historical
        values = {11: 11, 12: 50, 21: 5}
        return {p['player_id']: PlayerDistribution([[values[p['player_id']], *([0] * (len(COMPONENTS) - 1))]], [1])
                for p in players}, []

    monkeypatch.setattr(timeline, '_daily_box', lambda *args: [match])
    monkeypatch.setattr(timeline, '_finished_game', finished)
    monkeypatch.setattr(timeline, 'build_distributions', histories)
    return meta


def test_timeline_uses_final_whistles_and_only_credited_statistics(monkeypatch):
    meta = setup(monkeypatch)
    now = START + timedelta(days=1)
    data = timeline.get_matchup_timeline(meta, 1, 1, now=now)
    points = data['points']
    assert [point['game_id'] for point in points] == [None, 102, 101]
    # Actual 1 from game 101 is revealed only at its final whistle and
    # the bench player's 999 points are never credited.
    assert [point['p_win'] for point in points] == [1, 1, 0]
    assert points[-1]['final'] is True
    assert all(point['p_win'] + point['p_tie'] + point['p_loss'] == 1 for point in points)
    opposite = timeline.get_matchup_timeline(meta, 2, 1, now=now)['points']
    assert [p['p_loss'] for p in opposite] == [p['p_win'] for p in points]


def test_timeline_waits_for_current_fantasy_score_to_catch_up(monkeypatch):
    meta = setup(monkeypatch, partial=True)
    points = timeline.get_matchup_timeline(meta, 1, 1, now=START + timedelta(hours=5))['points']
    assert [point['game_id'] for point in points] == [None]
    assert points[0]['p_win'] == 1


def test_timeline_shows_opening_odds_before_tipoff_and_until_first_final(monkeypatch):
    meta = setup(monkeypatch, partial=True)
    meta.league.scoringPeriodId = 0
    before = timeline.get_matchup_timeline(meta, 1, 1, now=START - timedelta(minutes=30))['points']

    meta.league.scoringPeriodId = 1
    monkeypatch.setattr(timeline, '_finished_game', lambda *args: None)
    after = timeline.get_matchup_timeline(meta, 1, 1, now=START + timedelta(minutes=30))['points']

    assert before == after
    assert len(before) == 1
    assert before[0]['game_id'] is None
    assert before[0]['p_win'] == 1
