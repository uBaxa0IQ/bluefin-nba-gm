"""Freeze playoff dates, official seeds and any matchups already published by ESPN."""
from collections import Counter

from espn_api.basketball.constant import STATS_MAP
from espn_api.requests.espn_requests import ESPNAccessDenied, ESPNInvalidLeague, ESPNUnknownError
from requests import RequestException

from core.monte_carlo import COMPONENTS, RATIOS, WeekPlan
from core.playoff import playoff_scoring_calendar
from core.playoff_simulation import PlayoffRound, Postseason
from .live_matchups import read_fantasy_day


BRACKETS = {'WINNERS_BRACKET': 'championship', 'WINNERS_CONSOLATION_LADDER': 'placement',
            'LOSERS_CONSOLATION_LADDER': 'consolation'}


def _published_round(league, raw, period, day, seeds, sizes):
    rows = [m for m in raw.get('schedule', ()) if m.get('matchupPeriodId') == period]
    if len(rows) != sum(sizes.values()) or any(m.get('playoffTierType') not in BRACKETS for m in rows):
        try:
            rows = [m for m in read_fantasy_day(league, period, day).get('schedule', ())
                    if m.get('matchupPeriodId') == period]
        except (RequestException, ESPNAccessDenied, ESPNInvalidLeague, ESPNUnknownError) as err:
            raise ValueError('ESPN не отдал официальную сетку плей-офф.') from err
    result = []
    for row in sorted(rows, key=lambda m: m.get('id', 0)):
        kind = BRACKETS.get(row.get('playoffTierType'))
        a, b = ((row.get(side) or {}).get('teamId') for side in ('home', 'away'))
        if not kind or a not in seeds or b not in seeds:
            raise ValueError('ESPN ещё не опубликовал все пары этого раунда.')
        winner = {'HOME': a, 'AWAY': b}.get(row.get('winner'))
        if row.get('winner') == 'TIE':
            winner = min((a, b), key=seeds.index)
        result.append((kind, a, b, winner))
    actual_sizes = Counter(kind for kind, *_ in result)
    paired = [tid for _, a, b, _ in result for tid in (a, b)]
    if actual_sizes != Counter(sizes) or sorted(paired) != sorted(seeds):
        raise ValueError('Опубликованная сетка ESPN расходится с настройками плей-офф.')
    return tuple(result)


def prepare_postseason(league, raw, teams, current, build_week):
    schedule = raw['settings']['scheduleSettings']
    team_count = len(teams)
    if (int(league.settings.playoff_team_count) != 8 or schedule.get('playoffReseed')
            or team_count < 8 or team_count % 2 or schedule.get('consolationLadderDisabled')):
        raise ValueError('Поддерживается сетка на 8 команд без перепосева с утешительными матчами.')
    calendar = playoff_scoring_calendar(league)
    if len(calendar) != 3:
        raise ValueError('Поддерживается плей-офф из трёх раундов.')
    scoring = raw['settings'].get('scoringSettings', {})
    rule = scoring.get('playoffMatchupTieRule')
    tie = None
    if rule == 'STAT_POINTS':
        tie = STATS_MAP.get(str(scoring.get('playoffMatchupTieRuleBy', 0)))
        if tie not in (*COMPONENTS, *RATIOS):
            raise ValueError('Категория тай-брейка плей-офф не поддерживается.')
    elif rule not in ('NONE', 'HIGHER_SEED', None):
        raise ValueError('Тай-брейк плей-офф не поддерживается.')

    seeds = ()
    if current >= min(calendar):
        lookup = {t['playoffSeed']: t['id'] for t in raw.get('teams', ())
                  if t.get('playoffSeed') and t.get('id') is not None}
        if set(lookup) != set(range(1, team_count+1)) or set(lookup.values()) != {t['team_id'] for t in teams}:
            raise ValueError('ESPN ещё не опубликовал официальный посев.')
        seeds = tuple(lookup[i] for i in range(1, team_count+1))
    today = int(league.scoringPeriodId)
    rounds = []
    for i, (period, (days, start, end)) in enumerate(calendar.items()):
        official = ()
        if period <= current:
            sizes = {'championship': (4, 2, 1)[i], 'placement': (0, 2, 3)[i],
                     'consolation': (team_count-8)//2}
            official = _published_round(league, raw, period, min(today, days[-1]), seeds, sizes)
        if period < current or today > days[-1]:
            if any(m[-1] is None for m in official):
                raise ValueError('ESPN ещё не опубликовал итог завершённого раунда.')
            plan = WeekPlan(period, {}, ())
        else:
            # At tipoff switch from forecast totals to ESPN credits plus remaining games.
            remaining = [day for day in days if day >= today] if period == current else days
            plan = build_week(period, remaining, ())
        rounds.append(PlayoffRound(plan, start, end, official))
    return Postseason(tuple(rounds), seeds, tie)
