from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

from core import analytics_cache as cache


def inputs():
    player = SimpleNamespace(playerId=11, name='A', stats={'total': {'PTS': 10}},
        schedule={'1': {'date': datetime.fromtimestamp(1800000000)}}, eligibleSlots=['PG'])
    team = SimpleNamespace(team_id=1, team_name='Team', roster=[player], wins=2)
    return SimpleNamespace(league_id=1, year=2027, teams=[team],
        league=SimpleNamespace(current_week=1)), {'settings': {'slots': {'PG': 1}},
        'schedule': [{'home': {'totalPoints': 5}, 'away': {'totalPoints': 4}}]}


def test_data_hash_ignores_fetch_time_but_tracks_stats_score_and_rosters(monkeypatch):
    monkeypatch.setattr(cache.time, 'time', lambda: 1799999900)
    meta, raw = inputs()
    cache.capture_league_inputs(meta, raw)
    original = cache.analytics_version(meta)
    meta.last_refresh_time = datetime.now()
    cache.capture_league_inputs(meta, deepcopy(raw))
    assert cache.analytics_version(meta) == original
    meta.teams[0].roster[0].stats['total']['PTS'] = 11
    cache.capture_league_inputs(meta, raw)
    assert cache.analytics_version(meta) != original
    previous = cache.analytics_version(meta)
    raw['schedule'][0]['home']['totalPoints'] = 6
    cache.capture_league_inputs(meta, raw)
    assert cache.analytics_version(meta) != previous
    previous = cache.analytics_version(meta)
    meta.teams[0].roster = []
    cache.capture_league_inputs(meta, raw)
    assert cache.analytics_version(meta) != previous


def test_started_game_and_coefficients_invalidate_cache(monkeypatch):
    meta, raw = inputs()
    cache.capture_league_inputs(meta, raw)
    monkeypatch.setattr(cache.time, 'time', lambda: 1799999999)
    before = cache.analytics_version(meta)
    monkeypatch.setattr(cache.time, 'time', lambda: 1800000001)
    assert cache.analytics_version(meta) != before
    before = cache.analytics_version(meta)
    monkeypatch.setattr(cache, 'load_weighted_coefficients', lambda: {'total': .5, 'last_7': .5})
    assert cache.analytics_version(meta) != before
