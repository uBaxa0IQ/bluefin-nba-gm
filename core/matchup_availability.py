"""Availability of played matchup statistics, independent of ESPN's week rollover."""


def latest_stats_week(metadata, current_week):
    teams = metadata.get_teams()
    for week in range(current_week, 0, -1):
        for team in teams:
            box = metadata.get_matchup_box_score(week, team.team_id)
            if box and any(value for value in box.get('totals', {}).values()
                           if isinstance(value, (int, float))):
                return week
    return None
