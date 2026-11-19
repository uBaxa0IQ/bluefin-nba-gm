"""Calendar adapter for the pure Monte Carlo engine. Does not modify league data."""
from collections import Counter, defaultdict

from core.monte_carlo import WeekPlan, COMPONENTS, RATIOS
from core.projection import build_matchup_lineups, get_matchup_scoring_periods, get_remaining_scoring_periods, roster_available_on
from core.snapshot import build_league_snapshot
from core.simulation import compare_category_stats
from .projections import projection_injury_context, projection_snapshot_options, select_projection_roster


def prepare_season(metadata, period, *, simulation_mode='top_n', top_n_players=13,
                   custom_rosters=None, punt_categories=(), snapshot=None, punt_team_id=None):
    league = metadata.league
    snapshot = snapshot or build_league_snapshot(metadata, period, **projection_snapshot_options(simulation_mode))
    injury_context = projection_injury_context(metadata, snapshot, simulation_mode,
        punt_team_id=punt_team_id, punt_categories=punt_categories)
    raw = getattr(metadata, 'league_data', None) or league.espn_request.get_league()
    schedule_settings = raw['settings']['scheduleSettings']
    divisions = schedule_settings.get('divisions', [])
    if len(divisions) > 1 or metadata.scoring_type != 'H2H_MOST_CATEGORIES':
        raise ValueError('v1 requires H2H_MOST_CATEGORIES with a single division')
    if schedule_settings.get('playoffSeedingRule', 'H2H_RECORD') != 'H2H_RECORD':
        raise ValueError('v1 supports the H2H_RECORD playoff seeding rule')
    scoring = raw['settings'].get('scoringSettings', {})
    tie_rule = scoring.get('matchupTieRule', 'NONE')
    tie_category = None
    if tie_rule == 'STAT_POINTS':
        from espn_api.basketball.constant import STATS_MAP
        tie_category = STATS_MAP.get(str(scoring.get('matchupTieRuleBy', 0)))
        if tie_category not in (*COMPONENTS, *RATIOS):
            raise ValueError('Unsupported weekly tiebreak category')
    elif tie_rule not in ('NONE', None):
        raise ValueError('Unsupported weekly tie rule')
    teams = [{'team_id': t.team_id, 'team_name': t.team_name,
              'wins': int(t.wins), 'losses': int(t.losses), 'ties': int(t.ties)} for t in metadata.get_teams()]
    ids = {t['team_id'] for t in teams}
    current, final = int(league.currentMatchupPeriod), int(league.settings.reg_season_count)
    pairs = defaultdict(list)
    completed_outcomes = {}
    official_winners = {'HOME': 1, 'AWAY': -1, 'TIE': 0}
    # Read once, fail closed instead of silently forecasting an incomplete schedule.
    seen = set()
    for match in raw.get('schedule', []):
        week = int(match.get('matchupPeriodId', 0))
        a, b = match.get('home', {}).get('teamId'), match.get('away', {}).get('teamId')
        if not (1 <= week <= final) or not a or not b:
            continue
        identity = (week, frozenset((a, b)))
        if identity in seen:
            raise ValueError(f'Duplicate official matchup: {identity}')
        if a not in ids or b not in ids:
            raise ValueError('Schedule references an unknown fantasy team')
        seen.add(identity)
        pairs[week].append((a, b))
        winner = match.get('winner')
        if week < current and winner in official_winners:
            completed_outcomes[week, a, b] = official_winners[winner]
    for week in range(1, final + 1):
        counts = Counter(t for pair in pairs[week] for t in pair)
        if len(teams) % 2 == 0 and (set(counts) != ids or set(counts.values()) != {1}):
            raise ValueError(f'Incomplete official schedule in week {week}')

    categories, reverse = metadata.get_categories(), metadata.reverse_categories
    historical, historical_record = [], {t: [0, 0, 0] for t in ids}
    for week in range(1, min(current, final + 1)):
        stats = None
        for a, b in pairs[week]:
            outcome = completed_outcomes.get((week, a, b))
            if outcome is None:
                # Some archived schedules lack a final winner. Read box scores
                # only for those matchups, at most once per week.
                if stats is None:
                    stats = metadata.get_all_teams_stats_for_week(week)
                if a not in stats or b not in stats:
                    raise ValueError(f'ESPN не отдал итог матчапа за неделю {week}. Повторите расчёт позже.')
                left, right = stats[a]['stats'], stats[b]['stats']
                comparison = compare_category_stats(left, right, categories, reverse)
                wins, losses = comparison['team1_wins'], comparison['team2_wins']
                outcome = int(wins > losses) - int(wins < losses)
                if outcome == 0 and tie_category:
                    delta = left.get(tie_category, 0) - right.get(tie_category, 0)
                    if tie_category in reverse:
                        delta = -delta
                    outcome = int(delta > 0) - int(delta < 0)
            historical.append((a, b, outcome))
            historical_record[a][0 if outcome > 0 else 1 if outcome < 0 else 2] += 1
            historical_record[b][0 if outcome < 0 else 1 if outcome > 0 else 2] += 1
    for team in teams:
        if historical_record[team['team_id']] != [team[k] for k in ('wins', 'losses', 'ties')]:
            raise ValueError(f"Official record and completed schedule disagree for {team['team_name']}; refresh league data")

    selected, timelines = {}, {}
    for team in teams:
        team_id = team['team_id']
        custom = (custom_rosters or {}).get(team_id, ())
        roster = [p.as_projection_player() for p in snapshot.team_players(team_id)]
        if custom and not set(custom).issubset({p['name'] for p in roster}):
            raise ValueError(f'Stale custom roster for team {team_id}')
        timeline = {}
        selected[team_id] = select_projection_roster(roster, simulation_mode, top_n_players, custom,
                                                    injury_context=injury_context, team_id=team_id, timeline=timeline)
        if injury_context:
            timelines[str(team_id)] = timeline
    plans, scheduled_players = [], {}
    for week in range(current, final + 1):
        days = get_remaining_scoring_periods(league, week) if week == current else get_matchup_scoring_periods(league, week)
        if not days:
            # A fully played current week can have no remaining days; future weeks cannot.
            if week > current:
                raise ValueError(f'Missing NBA scoring days for week {week}')
        actual, games = {}, {}
        for team in teams:
            team_id = team['team_id']
            players = [{**p, 'future_only': week == current, 'as_of': snapshot.created_at}
                       for p in selected[team_id]]
            team_punts = injury_context.punts_for(team_id) if injury_context else punt_categories
            lineup = build_matchup_lineups(players, days, slots=snapshot.active_slots, punt_categories=team_punts)
            games[team_id] = {}
            for player in players:
                count = lineup['selected_games'].get(player['name'], 0)
                if count:
                    pid = player['player_id']
                    if pid is None:
                        raise ValueError(f"Missing player ID: {player['name']}")
                    games[team_id][pid] = count
                    scheduled_players[pid] = player
            if week == current:
                box = metadata.get_matchup_box_score(week, team_id)
                totals = box['totals'] if box else {}
                if any(totals.get(c, 0) for c in COMPONENTS):
                    required = set(COMPONENTS) - {'DD'}
                    missing = required - totals.keys()
                    if missing:
                        raise ValueError(f'Current-week credited shot components missing for team {team_id}: {sorted(missing)}')
                actual[team_id] = totals
        plans.append(WeekPlan(week, games, tuple(pairs[week]), actual))
    return {'teams': teams, 'weeks': plans, 'players': list(scheduled_players.values()),
            'historical_h2h': historical, 'categories': categories, 'reverse_categories': sorted(reverse),
            'matchup_tie_category': tie_category,
            'playoff_teams': int(league.settings.playoff_team_count),
            'metadata': {'league_id': metadata.league_id, 'season': metadata.year, 'period': period,
                         'current_week': current, 'regular_season_end': final,
                         'as_of': snapshot.created_at.isoformat(), 'simulation_mode': simulation_mode,
                         'top_n_players': top_n_players, 'punt_categories': list(punt_categories),
                         'rosters': {str(t): [p['name'] for p in roster
                                              if injury_context is None or roster_available_on(p, injury_context.as_of)]
                                     for t, roster in selected.items()},
                         **({'roster_timelines': timelines, 'roster_limit': injury_context.roster_limit, 'punt_team_id': punt_team_id,
                             'injury_report_at': injury_context.updated_at} if injury_context else {}),
                         'scoring_type': metadata.scoring_type,
                         'playoff_seeding_rule': schedule_settings.get('playoffSeedingRule')}}


def save_inputs(path, prepared, distributions, coverage):
    """Credential-free portable inputs: rerun a frozen calculation without ESPN."""
    from dataclasses import asdict
    import json
    from pathlib import Path
    document = {k: v for k, v in prepared.items() if k not in ('weeks', 'players')}
    document['weeks'] = [asdict(w) for w in prepared['weeks']]
    document['distributions'] = {str(pid): {'samples': d.samples.tolist(), 'weights': d.weights.tolist(), 'source': d.source}
                                 for pid, d in distributions.items()}
    document['coverage'] = coverage
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def load_inputs(path):
    import json
    from pathlib import Path
    from core.monte_carlo import PlayerDistribution
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    data['weeks'] = [WeekPlan(w['week'], {int(t): {int(p): n for p, n in games.items()} for t, games in w['games'].items()},
                              tuple(tuple(pair) for pair in w['official_pairs']),
                              {int(t): stats for t, stats in w['actual'].items()}) for w in data['weeks']]
    distributions = {int(pid): PlayerDistribution(d['samples'], d['weights'], d['source'])
                     for pid, d in data.pop('distributions').items()}
    return data, distributions
