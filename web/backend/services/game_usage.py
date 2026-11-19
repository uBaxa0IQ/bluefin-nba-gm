"""Count fantasy player-games from ESPN's daily lineups and NBA schedule."""

from datetime import datetime
from time import monotonic

from core.projection import get_matchup_scoring_periods, has_game, optimize_daily_lineup
from core.analytics_cache import analytics_version
from core.config import DEFAULT_PERIOD
from core.injuries import INJURY_MODE
from core.roster_rules import league_slots
from core.snapshot import build_league_snapshot
from .projections import projection_injury_context, projection_snapshot_options, select_projection_roster


def _player_row(player):
    return {
        "name": player.name,
        "position": getattr(player, "position", ""),
        "eligible_slots": getattr(player, "eligibleSlots", []),
        "lineup_value": 1,
    }


def _played(player, day):
    stats = (getattr(player, "stats", {}) or {}).get(str(day), {})
    return float((stats.get("total") or {}).get("GP", 0) or 0) > 0


def _game_on_day(player, day, *, unstarted=False):
    game = (getattr(player, "schedule", {}) or {}).get(str(day))
    if not game:
        return False
    if not unstarted:
        return True
    game_date = game.get("date")
    if not isinstance(game_date, datetime):
        return False
    now = datetime.now(game_date.tzinfo) if game_date.tzinfo else datetime.now()
    return game_date > now


def _max_games(players, slots):
    return len(optimize_daily_lineup([_player_row(player) for player in players], slots, fill_slots=True)["starters"])


def get_week_game_usage(league_meta, team_ids, *, period=None, simulation_mode="all",
                        top_n_players=13, custom_team_id=None, custom_team_players=(),
                        punt_team_id=None, punt_categories=()):
    """Return counted games and projected week totals for the matchup teams."""
    league = league_meta.league
    week = int(league.currentMatchupPeriod)
    current_day = int(league.scoringPeriodId)
    injury_aware = simulation_mode == INJURY_MODE
    injury_version = analytics_version(league_meta, injury_aware=True) if injury_aware else None
    selected_ids = tuple(sorted(int(team_id) for team_id in team_ids))
    cache_key = (week, current_day, selected_ids, period, simulation_mode,
                 top_n_players, custom_team_id, tuple(custom_team_players), injury_version, punt_team_id, tuple(punt_categories))
    cache = getattr(league_meta, "_game_usage_cache", None)
    if cache and cache[0] == cache_key and monotonic() - cache[1] < 60:
        return cache[2]

    days = get_matchup_scoring_periods(league, week)
    slots = league_slots(league_meta)
    active_slots = set(slots)
    teams = [team for team in league_meta.get_teams() if team.team_id in selected_ids]
    rows = {
        team.team_id: {
            "played": 0,
            "projected_total": 0,
        }
        for team in teams
    }
    current_lineups = {}

    for day in days:
        if day > current_day:
            continue
        boxes = league.box_scores(matchup_period=week, scoring_period=day, matchup_total=False)
        for box in boxes:
            for team, lineup in ((box.home_team, box.home_lineup), (box.away_team, box.away_lineup)):
                team_id = getattr(team, "team_id", None)
                if team_id not in rows:
                    continue
                played_players = [player for player in lineup if _played(player, day)]
                actual = sum(getattr(player, "slot_position", "") in active_slots for player in played_players)
                rows[team_id]["played"] += actual
                if day == current_day:
                    current_lineups[team_id] = played_players

    snapshot = (build_league_snapshot(league_meta, period or DEFAULT_PERIOD, **projection_snapshot_options(simulation_mode))
                if simulation_mode in {"top_n", INJURY_MODE} else None)
    injury_context = projection_injury_context(league_meta, snapshot, simulation_mode,
        punt_team_id=punt_team_id, punt_categories=punt_categories)
    for team in teams:
        row = rows[team.team_id]
        selection_pool = (
            [player.as_projection_player() for player in snapshot.team_players(team.team_id)]
            if snapshot else [
                {**_player_row(player), "lineup_slot": getattr(player, "lineupSlot", "")}
                for player in team.roster
            ]
        )
        planned = {p['name']: p for p in select_projection_roster(
            selection_pool, simulation_mode, top_n_players,
            custom_team_players if team.team_id == custom_team_id else (),
            injury_context=injury_context, team_id=team.team_id,
        )}
        roster = [player for player in team.roster if player.name in planned]
        remaining = 0
        for day in days:
            if day < current_day:
                continue
            if day == current_day:
                played_players = current_lineups.get(team.team_id, [])
                used_slots = [player.slot_position for player in played_players if player.slot_position in active_slots]
                open_slots = list(slots)
                for slot in used_slots:
                    if slot in open_slots:
                        open_slots.remove(slot)
                played_ids = {player.playerId for player in played_players}
                candidates = [
                    player for player in roster
                    if player.playerId not in played_ids and _game_on_day(player, day, unstarted=True)
                ]
            else:
                open_slots = slots
                candidates = [player for player in roster if _game_on_day(player, day)]
            if injury_context:
                candidates = [p for p in candidates if has_game(planned[p.name], day)]
            remaining += _max_games(candidates, open_slots)
        row["projected_total"] = row["played"] + remaining

    league_meta._game_usage_cache = (cache_key, monotonic(), rows)
    return rows
