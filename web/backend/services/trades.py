"""Trade impact on the selected roster, calendar and daily lineup slots."""


from core.config import CATEGORIES
from core.projection import (
    get_matchup_scoring_periods,
    get_remaining_scoring_periods,
)
from core.snapshot import build_league_snapshot
from .projections import projection_injury_context, projection_snapshot_options, select_projection_roster
from .live_matchups import current_matchup, future_lineups, future_stats


def _project(players, scoring_periods, punts, slots, current, team_id, live_players, live):
    lineup = future_lineups(players, scoring_periods, slots, punts, current=current, team_id=team_id)
    stats = future_stats(players, lineup, live_players, live)
    value = sum(day["total_value"] for day in lineup["days"])
    return value, stats, sum(lineup["selected_games"].values())


def analyze_calendar_trade(league_metadata, period, team_moves, punt_categories=(),
                           selected_before=None, selected_after=None, simulation_mode="all", punt_team_id=None):
    """Evaluate roster moves in the actual remaining matchup calendar."""
    snapshot = build_league_snapshot(league_metadata, period, **projection_snapshot_options(simulation_mode))
    injury_context = projection_injury_context(league_metadata, snapshot, simulation_mode,
        punt_team_id=punt_team_id, punt_categories=punt_categories)
    league = league_metadata.league
    matchup_period = int(league.currentMatchupPeriod)
    scoring_periods = get_remaining_scoring_periods(league, matchup_period)
    if not scoring_periods:
        scoring_periods = get_matchup_scoring_periods(league, matchup_period)

    all_players = {
        player.name: {**player.as_projection_player(), 'future_only': True}
        for player in snapshot.players
    }
    current = current_matchup(league_metadata, matchup_period, snapshot.active_slots)
    live_players = {player['player_id']: player for player in all_players.values()} if current.confirmed else {}
    teams = {}
    for team_id, move in team_moves.items():
        before = [{**player.as_projection_player(), 'future_only': True} for player in snapshot.team_players(team_id)]
        after = [player for player in before if player["name"] not in move["give"]]
        after.extend({**all_players[name], 'lineup_slot': 'BE'} if injury_context else all_players[name]
                     for name in move["receive"] if name in all_players)
        before_timeline, after_timeline = {}, {}
        before = select_projection_roster(
            before, simulation_mode, custom_team_players=(selected_before or {}).get(team_id, ()),
            injury_context=injury_context, team_id=team_id, timeline=before_timeline,
        )
        after = select_projection_roster(
            after, simulation_mode, custom_team_players=(selected_after or {}).get(team_id, ()),
            injury_context=injury_context, team_id=team_id, timeline=after_timeline,
        )
        if selected_before and team_id in selected_before:
            before = [player for player in before if player['name'] in selected_before[team_id]]
        if selected_after and team_id in selected_after:
            after = [player for player in after if player['name'] in selected_after[team_id]]
        team_punts = injury_context.punts_for(team_id) if injury_context else punt_categories
        args = (scoring_periods, team_punts, snapshot.active_slots, current, team_id,
                live_players, current.remainders(team_id, live_players))
        before_value, before_stats, before_games = _project(before, *args)
        after_value, after_stats, after_games = _project(after, *args)
        teams[team_id] = {
            "before_value": round(before_value, 3),
            "after_value": round(after_value, 3),
            "delta": round(after_value - before_value, 3),
            "selected_games_before": before_games,
            "selected_games_after": after_games,
            **({"roster_timeline": {"before": before_timeline, "after": after_timeline}} if injury_context else {}),
            "category_delta": {
                category: round(after_stats.get(category, 0) - before_stats.get(category, 0), 4)
                for category in CATEGORIES
                if category not in team_punts
            },
        }
    return {
        "method": "remaining_calendar_and_daily_slots",
        "scope_note": "Календарная дельта относится только к текущему матчапу. Для долгосрочного обмена сравните также статистику состава за сезон.",
        "matchup_period": matchup_period,
        "scoring_periods": scoring_periods,
        "teams": teams,
    }
