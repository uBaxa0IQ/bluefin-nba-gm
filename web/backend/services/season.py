"""Прогноз регулярного сезона на официальном ESPN schedule."""

from collections import defaultdict
from typing import Any, Dict

from core.projection import get_matchup_scoring_periods, get_remaining_scoring_periods, project_team_stats
from core.roster_rules import static_roster_mode
from core.matchup_value import combine_stats
from core.simulation import compare_category_stats
from core.snapshot import build_league_snapshot
from .projections import project_snapshot_for_matchup, projection_injury_context, projection_snapshot_options, select_projection_roster
from .forecast_history import record
from .live_matchups import current_matchup, current_totals
from core.config import CATEGORIES, REVERSE_CATEGORIES
import logging
import sqlite3


def project_regular_season(league_metadata, period: str, calculation_engine: str = "calendar",
                           simulation_mode="all", top_n_players=13,
                           custom_team_id=None, custom_team_players=(), snapshot_override=None,
                           custom_rosters=None, punt_categories=(), record_forecasts=True, punt_team_id=None,
                           current=None) -> Dict[str, Any]:
    if calculation_engine == "legacy":
        simulation_mode = static_roster_mode(simulation_mode)
    league = league_metadata.league
    teams = league_metadata.get_teams()
    regular_season_end = int(league.settings.reg_season_count)
    current_period = int(league.currentMatchupPeriod)
    first_projection_period = min(current_period, regular_season_end + 1)

    records = {
        team.team_id: {
            "wins": int(getattr(team, "wins", 0) or 0),
            "losses": int(getattr(team, "losses", 0) or 0),
            "ties": int(getattr(team, "ties", 0) or 0),
        }
        for team in teams
    }
    projected_matchups = defaultdict(list)

    has_future_matchups = first_projection_period <= regular_season_end
    injury_context, timelines, planned_rosters = None, {}, None
    if has_future_matchups:
        snapshot = snapshot_override or build_league_snapshot(league_metadata, period, **projection_snapshot_options(simulation_mode))
        injury_context = projection_injury_context(league_metadata, snapshot, simulation_mode,
            punt_team_id=punt_team_id, punt_categories=punt_categories)
        if injury_context:
            planned_rosters = {}
            for team in teams:
                roster = [p.as_projection_player() for p in snapshot.team_players(team.team_id)]
                planned_rosters[team.team_id], timelines[team.team_id] = injury_context.plan(roster, team.team_id)
        legacy_team_stats = None
        if calculation_engine == "legacy":
            legacy_team_stats = {}
            for team in teams:
                players = select_projection_roster(
                    [player.as_projection_player() for player in snapshot.team_players(team.team_id)],
                    simulation_mode, top_n_players,
                    custom_team_players if team.team_id == custom_team_id else (),
                )
                selected_games = {player["name"]: 1 for player in players if player.get("available", True)}
                legacy_team_stats[team.team_id] = {
                    "name": team.team_name,
                    "stats": project_team_stats(players, selected_games),
                }
        schedule = league_metadata.get_schedule_matchups(
            first_projection_period,
            regular_season_end,
        )
        schedule_by_period = defaultdict(list)
        for matchup in schedule:
            schedule_by_period[matchup["matchup_period"]].append(matchup)

        for matchup_period in range(first_projection_period, regular_season_end + 1):
            scoring_periods = get_matchup_scoring_periods(league, matchup_period)
            if legacy_team_stats is not None:
                team_stats = legacy_team_stats
            else:
                if matchup_period == current_period:
                    scoring_periods = get_remaining_scoring_periods(league, matchup_period)
                    current = current or current_matchup(league_metadata, current_period, snapshot.active_slots)
                team_stats, _ = project_snapshot_for_matchup(
                    snapshot, teams, scoring_periods, future_only=matchup_period == current_period,
                    simulation_mode=simulation_mode, top_n_players=top_n_players,
                    custom_team_id=custom_team_id, custom_team_players=custom_team_players,
                    custom_rosters=custom_rosters, punt_categories=punt_categories,
                    planned_rosters=planned_rosters, injury_context=injury_context,
                    current=current if matchup_period == current_period else None,
                )
                if matchup_period == current_period:
                    for team in teams:
                        actual = current_totals(league_metadata, matchup_period, team.team_id, current)
                        if actual:
                            team_stats[team.team_id]['stats'] = combine_stats(actual, team_stats[team.team_id]['stats'])
            for matchup in schedule_by_period[matchup_period]:
                team1_id = matchup["team1_id"]
                team2_id = matchup["team2_id"]
                if record_forecasts and matchup_period > current_period and calculation_engine == 'calendar' and simulation_mode == 'all':
                    try:
                        record(league_metadata.league_id, league_metadata.year, matchup_period, team1_id, team2_id, period,
                               team_stats[team1_id]['stats'], team_stats[team2_id]['stats'], CATEGORIES, REVERSE_CATEGORIES)
                    except (OSError, sqlite3.Error):
                        logging.getLogger(__name__).warning('Не удалось сохранить прогноз для последующей проверки')
                comparison = compare_category_stats(
                    team_stats[team1_id]["stats"],
                    team_stats[team2_id]["stats"],
                )
                wins1 = comparison["team1_wins"]
                wins2 = comparison["team2_wins"]
                if wins1 > wins2:
                    result1, result2 = "win", "loss"
                    records[team1_id]["wins"] += 1
                    records[team2_id]["losses"] += 1
                elif wins2 > wins1:
                    result1, result2 = "loss", "win"
                    records[team2_id]["wins"] += 1
                    records[team1_id]["losses"] += 1
                else:
                    result1 = result2 = "tie"
                    records[team1_id]["ties"] += 1
                    records[team2_id]["ties"] += 1

                projected_matchups[team1_id].append(
                    {"week": matchup_period, "opponent_id": team2_id, "result": result1,
                     "score": f"{wins1}-{wins2}", "categories": comparison["categories"]}
                )
                projected_matchups[team2_id].append(
                    {"week": matchup_period, "opponent_id": team1_id, "result": result2,
                     "score": f"{wins2}-{wins1}", "categories": {
                         category: "loss" if outcome == "win" else "win" if outcome == "loss" else "tie"
                         for category, outcome in comparison["categories"].items()
                     }}
                )

    standings = []
    teams_by_id = {team.team_id: team for team in teams}
    for team_id, team_record in records.items():
        total = team_record["wins"] + team_record["losses"] + team_record["ties"]
        win_rate = (team_record["wins"] + 0.5 * team_record["ties"]) / total if total else 0.0
        standings.append(
            {
                "team_id": team_id,
                "team_name": teams_by_id[team_id].team_name,
                "official_position": int(getattr(teams_by_id[team_id], "standing", 0) or 0),
                **team_record,
                "win_rate": round(win_rate * 100, 1),
                "projected_matchups": projected_matchups[team_id],
            }
        )

    if has_future_matchups:
        standings.sort(key=lambda item: (item["win_rate"], item["wins"]), reverse=True)
    else:
        standings.sort(key=lambda item: item["official_position"] or 10_000)
    for index, standing in enumerate(standings, start=1):
        standing["projected_position"] = index

    return {
        "period": period,
        "assumptions": ("Сила команд определяется средними показателями выбранных составов."
                        if calculation_engine == "legacy" else
                        ("Отчёт ESPN определяет даты возвращений и прогнозные дропы. " if injury_context else
                         "Выбранные игроки считаются доступными независимо от статуса травмы. ")
                        + "Текущая неделя включает зачтённую статистику ESPN, остаток сверенных матчей в процессе и прогноз ещё не начавшихся игр."),
        **({"roster_timelines": timelines, "injury_report_at": injury_context.updated_at} if injury_context else {}),
        "current_matchup_period": current_period,
        "regular_season_end": regular_season_end,
        "standings": standings,
        "tie_break_note": "Future ties are ordered by projected win rate and wins; ESPN applies the configured league tie-breaker.",
        "method": "legacy_team_averages" if calculation_engine == "legacy" else "schedule_projection",
    }
