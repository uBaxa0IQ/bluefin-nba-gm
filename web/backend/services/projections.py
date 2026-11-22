"""Оркестрация snapshot и projection engine для API."""

from typing import Any, Dict, Iterable, Optional
from core.injuries import INJURY_MODE
from core.roster_timeline import InjuryContext, overall_z

from core.projection import (
    get_matchup_scoring_periods,
    get_remaining_scoring_periods,
)
from core.snapshot import build_league_snapshot
from core.simulation import compare_category_stats, simulate_all_vs_all
from core.matchup_value import combine_stats, add_matchup_values
from .live_matchups import current_matchup, current_opponent, current_totals, future_lineups, future_stats


def projection_snapshot_options(mode):
    return {'include_unscored': True} if mode == INJURY_MODE else {}


def projection_injury_context(metadata, snapshot, mode, *, punt_team_id=None, punt_categories=()):
    if mode == INJURY_MODE:
        return InjuryContext.from_league(metadata, snapshot, punt_team_id=punt_team_id, punt_categories=punt_categories)
    return None


def injury_roster_today(metadata, period, *, punt_team_id=None, punt_categories=()):
    """Player rows for undated averages/Z views, after any same-day IR moves."""
    snapshot = build_league_snapshot(metadata, period, include_unscored=True)
    context = InjuryContext.from_league(metadata, snapshot, punt_team_id=punt_team_id, punt_categories=punt_categories)
    return [
        {**row, 'team_id': team.team_id, 'team_name': team.team_name}
        for team in metadata.get_teams()
        for row in context.available_today([p.as_projection_player() for p in snapshot.team_players(team.team_id)], team.team_id)
    ]


def select_projection_roster(players, simulation_mode="all", top_n_players=13, custom_team_players=(),
                             *, injury_context=None, team_id=None, timeline=None):
    """Apply the roster setting before choosing legal starters for each day."""
    if simulation_mode == INJURY_MODE:
        if injury_context is None:
            raise ValueError('Режиму травм требуется снимок доступности.')
        roster, details = injury_context.plan(players, team_id)
        if timeline is not None:
            timeline.update(details)
        return roster
    if simulation_mode not in {"all", "exclude_ir", "top_n"}:
        raise ValueError("Unknown roster mode")
    selected = [{**player, "available": True} for player in players]
    if simulation_mode == "exclude_ir":
        return [player for player in selected if str(player.get("lineup_slot") or "").upper() != "IR"]
    if simulation_mode == "top_n":
        names = set(custom_team_players)
        if names:
            return [player for player in selected if player.get("name") in names]
        return sorted(selected, key=overall_z, reverse=True)[:top_n_players]
    return selected


def project_team_matchup(
    league_metadata,
    team_id: int,
    period: str,
    matchup_period: Optional[int] = None,
    remaining_only: bool = False,
    punt_categories: Iterable[str] = (),
    simulation_mode: str = "all",
    top_n_players: int = 13,
    custom_team_players=(),
    punt_team_id=None,
) -> Dict[str, Any]:
    league = league_metadata.league
    matchup_period = matchup_period or int(league.currentMatchupPeriod)
    snapshot = build_league_snapshot(league_metadata, period, **projection_snapshot_options(simulation_mode))
    injury_context = projection_injury_context(league_metadata, snapshot, simulation_mode,
        punt_team_id=punt_team_id, punt_categories=punt_categories)
    team_punts = injury_context.punts_for(team_id) if injury_context else punt_categories
    if injury_context and matchup_period == int(league.currentMatchupPeriod):
        remaining_only = True
    team = league_metadata.get_team_by_id(team_id)
    if team is None:
        raise ValueError("Team not found")

    timeline = {}
    player_snapshots = snapshot.team_players(team_id)
    players = select_projection_roster(
        [{**player.as_projection_player(), 'future_only': remaining_only} for player in player_snapshots],
        simulation_mode, top_n_players, custom_team_players,
        injury_context=injury_context, team_id=team_id, timeline=timeline,
    )
    if remaining_only:
        scoring_periods = get_remaining_scoring_periods(league, matchup_period)
    else:
        scoring_periods = get_matchup_scoring_periods(league, matchup_period)

    opponent = None
    current = current_matchup(league_metadata, matchup_period, snapshot.active_slots) if remaining_only else None
    live_players = {p.player_id: p.as_projection_player() for p in snapshot.players} if current and current.confirmed else {}
    live = current.remainders(team_id, live_players) if current else {}
    if remaining_only:
        opponent_id = current_opponent(league_metadata, matchup_period, team_id, current)
        if opponent_id is not None:
            opponent_players = select_projection_roster(
                [{**p.as_projection_player(), 'future_only': True} for p in snapshot.team_players(opponent_id)],
                simulation_mode, top_n_players, injury_context=injury_context, team_id=opponent_id,
            )
            opponent_punts = injury_context.punts_for(opponent_id) if injury_context else punt_categories
            opponent_lineup = future_lineups(opponent_players, scoring_periods, snapshot.active_slots, opponent_punts,
                                             current=current, team_id=opponent_id)
            opponent_actual = current_totals(league_metadata, matchup_period, opponent_id, current)
            if opponent_actual:
                opponent = combine_stats(opponent_actual, future_stats(
                    opponent_players, opponent_lineup, live_players, current.remainders(opponent_id, live_players)))
                baseline = future_lineups(players, scoring_periods, snapshot.active_slots, team_punts,
                                          current=current, team_id=team_id)
                actual = current_totals(league_metadata, matchup_period, team_id, current)
                baseline_stats = combine_stats(actual, future_stats(players, baseline, live_players, live))
                players = add_matchup_values(players, baseline_stats, opponent, team_punts)
    lineup = future_lineups(players, scoring_periods, snapshot.active_slots, team_punts,
                            current=current, team_id=team_id, fill_slots=opponent is None)
    projected_stats = future_stats(players, lineup, live_players, live)

    days = []
    for day in lineup["days"]:
        days.append(
            {
                "scoring_period": day["scoring_period"],
                "starters": [
                    {
                        "slot": starter["slot"],
                        "name": starter["player"]["name"],
                        "position": starter["player"]["position"],
                        "value": round(starter["value"], 3),
                    }
                    for starter in day["starters"]
                ],
                "bench": [player["name"] for player in day["bench"]],
            }
        )

    return {
        "team_id": team_id,
        "team_name": team.team_name,
        "period": period,
        "matchup_period": matchup_period,
        "remaining_only": remaining_only,
        "scoring_periods": scoring_periods,
        "projected_stats": projected_stats,
        "selected_games": lineup["selected_games"],
        "days": days,
        "snapshot_created_at": snapshot.created_at.isoformat(),
        "objective": 'opponent_category_utility' if opponent is not None else 'games_then_z',
        "note": ("Прогноз учитывает травмы, даты активаций и прогнозные дропы."
                 if injury_context else "Прогноз по выбранному составу учитывает календарь и позиции.")
                + (" Для сверенных матчей в процессе прогнозируется остаток игры." if remaining_only else ""),
        **({"roster_timeline": timeline} if injury_context else {}),
    }


def project_league_matchup(
    league_metadata,
    period: str,
    matchup_period: Optional[int] = None,
    remaining_only: bool = False,
    punt_categories: Iterable[str] = (),
    simulation_mode: str = "all",
    top_n_players: int = 13,
    custom_team_id=None,
    custom_team_players=(),
    punt_team_id=None,
) -> Dict[str, Any]:
    league = league_metadata.league
    matchup_period = matchup_period or int(league.currentMatchupPeriod)
    snapshot = build_league_snapshot(league_metadata, period, **projection_snapshot_options(simulation_mode))
    injury_context = projection_injury_context(league_metadata, snapshot, simulation_mode,
        punt_team_id=punt_team_id, punt_categories=punt_categories)
    if injury_context and matchup_period == int(league.currentMatchupPeriod):
        remaining_only = True
    scoring_periods = (
        get_remaining_scoring_periods(league, matchup_period)
        if remaining_only
        else get_matchup_scoring_periods(league, matchup_period)
    )

    current = current_matchup(league_metadata, matchup_period, snapshot.active_slots) if remaining_only else None
    team_stats, team_projections = project_snapshot_for_matchup(
        snapshot,
        league_metadata.get_teams(),
        scoring_periods,
        punt_categories,
        future_only=remaining_only,
        simulation_mode=simulation_mode, top_n_players=top_n_players,
        custom_team_id=custom_team_id, custom_team_players=custom_team_players, injury_context=injury_context,
        current=current,
    )

    return {
        "mode": "schedule_projection",
        "period": period,
        "matchup_period": matchup_period,
        "remaining_only": remaining_only,
        "scoring_periods": scoring_periods,
        "results": simulate_all_vs_all(team_stats),
        "team_projections": team_projections,
        "snapshot_created_at": snapshot.created_at.isoformat(),
    }


def project_scheduled_matchups(league_metadata, period: str, matchup_period: int,
                               simulation_mode="all", top_n_players=13,
                               custom_team_id=None, custom_team_players=(), punt_team_id=None,
                               punt_categories=()) -> Dict[str, Any]:
    """Project only the pairs on ESPN's schedule for one fantasy week."""
    league = league_metadata.league
    matchup_period = int(matchup_period)
    current_period = int(league.currentMatchupPeriod)
    remaining_only = matchup_period == current_period
    scoring_periods = (
        get_remaining_scoring_periods(league, matchup_period)
        if remaining_only else get_matchup_scoring_periods(league, matchup_period)
    )
    snapshot = build_league_snapshot(league_metadata, period, **projection_snapshot_options(simulation_mode))
    injury_context = projection_injury_context(league_metadata, snapshot, simulation_mode,
        punt_team_id=punt_team_id, punt_categories=punt_categories)
    current = current_matchup(league_metadata, matchup_period, snapshot.active_slots) if remaining_only else None
    team_stats, _ = project_snapshot_for_matchup(
        snapshot, league_metadata.get_teams(), scoring_periods,
        future_only=remaining_only, simulation_mode=simulation_mode,
        top_n_players=top_n_players, custom_team_id=custom_team_id,
        custom_team_players=custom_team_players, injury_context=injury_context, punt_categories=punt_categories,
        current=current,
    )
    if remaining_only:
        for team_id, team in team_stats.items():
            actual = current_totals(league_metadata, matchup_period, team_id, current)
            if actual:
                team["stats"] = combine_stats(actual, team["stats"])

    categories = league_metadata.get_categories()
    reverse = league_metadata.reverse_categories
    matchups = []
    for pair in league_metadata.get_schedule_matchups(matchup_period, matchup_period):
        team1 = team_stats[pair["team1_id"]]
        team2 = team_stats[pair["team2_id"]]
        comparison = compare_category_stats(team1["stats"], team2["stats"], categories, reverse)
        matchups.append({
            "team1_id": pair["team1_id"], "team1_name": team1["name"],
            "team2_id": pair["team2_id"], "team2_name": team2["name"],
            "team1_wins": comparison["team1_wins"],
            "team2_wins": comparison["team2_wins"],
            "ties": len(categories) - comparison["team1_wins"] - comparison["team2_wins"],
            "categories": [
                {"name": category,
                 "team1": team1["stats"].get(category, 0.0),
                 "team2": team2["stats"].get(category, 0.0),
                 "winner": comparison["categories"][category]}
                for category in categories
            ],
        })
    return {
        "period": period,
        "matchup_period": matchup_period,
        "remaining_only": remaining_only,
        "scoring_periods": scoring_periods,
        "matchups": matchups,
    }


def project_snapshot_for_matchup(snapshot, teams, scoring_periods, punt_categories=(), future_only=False,
                                 simulation_mode="all", top_n_players=13,
                                 custom_team_id=None, custom_team_players=(), custom_rosters=None,
                                 injury_context=None, planned_rosters=None, current=None):
    """Проецирует все команды из одного snapshot для заданных scoring days."""
    team_stats = {}
    team_projections = {}
    live_players = {p.player_id: p.as_projection_player() for p in snapshot.players} if current and current.confirmed else {}
    for team in teams:
        if planned_rosters is not None:
            players = [{**p, 'future_only': future_only} for p in planned_rosters[team.team_id]]
        else:
            players = select_projection_roster([
                {**player.as_projection_player(), 'future_only': future_only}
                for player in snapshot.team_players(team.team_id)
            ], simulation_mode, top_n_players,
                (custom_rosters or {}).get(team.team_id, custom_team_players if team.team_id == custom_team_id else ()),
                injury_context=injury_context, team_id=team.team_id)
        team_punts = injury_context.punts_for(team.team_id) if injury_context else punt_categories
        lineup = future_lineups(players, scoring_periods, snapshot.active_slots, team_punts,
                                current=current, team_id=team.team_id)
        live = current.remainders(team.team_id, live_players) if current else {}
        stats = future_stats(players, lineup, live_players, live)
        team_stats[team.team_id] = {"name": team.team_name, "stats": stats}
        team_projections[team.team_id] = {
            "selected_games": lineup["selected_games"],
            "total_selected_games": sum(lineup["selected_games"].values()),
        }
    return team_stats, team_projections
