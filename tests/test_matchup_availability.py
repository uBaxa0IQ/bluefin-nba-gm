from types import SimpleNamespace

from core.matchup_availability import latest_stats_week


def metadata(boxes):
    return SimpleNamespace(
        get_teams=lambda: [SimpleNamespace(team_id=1), SimpleNamespace(team_id=2)],
        get_matchup_box_score=lambda week, team: boxes.get((week, team)),
    )


def test_rollover_uses_last_played_week():
    assert latest_stats_week(metadata({(4, 1): {'totals': {'PTS': 100}}}), 5) == 4


def test_zero_totals_do_not_start_a_week():
    assert latest_stats_week(metadata({
        (5, 1): {'totals': {'PTS': 0}},
        (4, 2): {'totals': {'PTS': 80}},
    }), 5) == 4


def test_started_week_is_available():
    assert latest_stats_week(metadata({(5, 2): {'totals': {'PTS': 2}}}), 5) == 5


def test_before_first_game_has_no_available_week():
    assert latest_stats_week(metadata({}), 1) is None
