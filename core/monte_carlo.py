"""Reproducible joint season simulation. No network, roster changes or injury draws."""
from dataclasses import dataclass, field
import math

import numpy as np

from .live_games import DOUBLE_DOUBLE_STATS, LiveGame

COMPONENTS = ('PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD',
              'FGM', 'FGA', 'FTM', 'FTA', '3PA', 'TO')
RATIOS = {'FG%': ('FGM', 'FGA'), 'FT%': ('FTM', 'FTA'),
          '3PT%': ('3PM', '3PA'), 'A/TO': ('AST', 'TO')}
INDEX = {key: i for i, key in enumerate(COMPONENTS)}


@dataclass(frozen=True)
class PlayerDistribution:
    """Rows are whole games, preserving their within-game stat dependence."""
    samples: np.ndarray
    weights: np.ndarray
    source: str = 'game_logs'

    def __post_init__(self):
        samples = np.array(self.samples, dtype=float, copy=True)
        weights = np.array(self.weights, dtype=float, copy=True)
        if samples.ndim != 2 or samples.shape[1] != len(COMPONENTS) or not len(samples):
            raise ValueError('Expected nonempty game rows with all component stats')
        if weights.shape != (len(samples),) or not np.all(np.isfinite(weights)) or np.any(weights < 0) or weights.sum() <= 0:
            raise ValueError('Invalid game weights')
        if not np.all(np.isfinite(samples)) or np.any(samples < 0):
            raise ValueError('Nonfinite or negative game statistics')
        samples.flags.writeable = False
        weights /= weights.sum()
        weights.flags.writeable = False
        object.__setattr__(self, 'samples', samples)
        object.__setattr__(self, 'weights', weights)


@dataclass(frozen=True)
class WeekPlan:
    week: int
    # Fixed legal starters chosen before seeing simulated results.
    games: dict[int, dict[int, int]]
    official_pairs: tuple[tuple[int, int], ...]
    actual: dict[int, dict[str, float]] = field(default_factory=dict)
    live_games: dict[int, dict[int, LiveGame]] = field(default_factory=dict)


def sample_remainder(distribution, game, trials, rng):
    rows = distribution.samples[rng.choice(len(distribution.samples), trials, p=distribution.weights)]

    def thin(counts):
        return rng.binomial(np.rint(np.maximum(counts, 0)).astype(int), game.fraction)

    def stat(key):
        return rows[:, INDEX[key]]

    result = np.zeros_like(rows)
    twos = thin(stat('FGM') - stat('3PM'))
    missed_twos = thin(stat('FGA') - stat('FGM') - (stat('3PA') - stat('3PM')))
    threes = thin(stat('3PM'))
    missed_threes = thin(stat('3PA') - stat('3PM'))
    free_throws = thin(stat('FTM'))
    result[:, INDEX['FGM']] = twos + threes
    result[:, INDEX['FGA']] = twos + threes + missed_twos + missed_threes
    result[:, INDEX['3PM']] = threes
    result[:, INDEX['3PA']] = threes + missed_threes
    result[:, INDEX['FTM']] = free_throws
    result[:, INDEX['FTA']] = free_throws + thin(stat('FTA') - stat('FTM'))
    result[:, INDEX['PTS']] = 2 * twos + 3 * threes + free_throws
    for key in ('REB', 'AST', 'STL', 'BLK', 'TO'):
        result[:, INDEX[key]] = thin(stat(key))
    if sum(game.actual.get(k, 0) >= 10 for k in DOUBLE_DOUBLE_STATS) < 2:
        columns = [INDEX[k] for k in DOUBLE_DOUBLE_STATS]
        current = [game.actual.get(k, 0) for k in DOUBLE_DOUBLE_STATS]
        result[:, INDEX['DD']] = ((result[:, columns] + current >= 10).sum(axis=1) >= 2)
    return result


def category_arrays(totals, categories):
    result = []
    for cat in categories:
        if cat in RATIOS:
            numerator, denominator = (totals[..., INDEX[x]] for x in RATIOS[cat])
            fallback = numerator.copy() if cat == 'A/TO' else np.zeros_like(numerator)
            result.append(np.divide(numerator, denominator, out=fallback, where=denominator != 0))
        else:
            result.append(totals[..., INDEX[cat]])
    return np.stack(result, axis=-1)


def rank_trial(points, games, h2h_points, h2h_games, rng):
    """Single-division ESPN H2H_RECORD: win rate, tied-group H2H, coin flip.

    Recompute the tied group after assigning each seed. H2H is used only
    when each team has played the same number of games in that group.
    """
    rates = points / np.maximum(games, 1)
    ordered = []
    for rate in sorted(set(rates.tolist()), reverse=True):
        remaining = [i for i, value in enumerate(rates) if value == rate]
        while remaining:
            candidates = remaining
            if len(remaining) > 1:
                counts = h2h_games[np.ix_(remaining, remaining)].sum(axis=1)
                if counts[0] > 0 and np.all(counts == counts[0]):
                    scored = h2h_points[np.ix_(remaining, remaining)].sum(axis=1)
                    candidates = [remaining[i] for i in np.flatnonzero(scored == scored.max())]
            chosen = candidates[int(rng.integers(len(candidates)))] if len(candidates) > 1 else candidates[0]
            ordered.append(chosen)
            remaining.remove(chosen)
    return ordered


def simulate_seasons(teams, weeks, distributions, *, categories, reverse_categories=(),
                     trials=10_000, seed=20261116, playoff_teams=8,
                     historical_h2h=(), all_opponents=True, matchup_tie_category=None,
                     paired_draws=False, injury_aware=False):
    """Probabilities are fractions in [0,1]; weeks are simulated jointly.

    teams: [{team_id, team_name, wins, losses, ties}]. historical_h2h:
    [(team1_id, team2_id, outcome)] with outcome 1/0/-1 for win/tie/loss.
    Standings support H2H_MOST_CATEGORIES and one division, checked by adapter.
    """
    if not isinstance(trials, int) or trials < 1 or trials > 100_000:
        raise ValueError('trials must be between 1 and 100,000')
    if not teams or len({t['team_id'] for t in teams}) != len(teams):
        raise ValueError('Expected unique nonempty teams')
    if not 0 <= playoff_teams <= len(teams):
        raise ValueError('Invalid playoff field')
    unknown = set(categories) - set(COMPONENTS) - set(RATIOS)
    if not categories or unknown:
        raise ValueError(f'Unsupported categories: {unknown}')
    if matchup_tie_category is not None and matchup_tie_category not in (*COMPONENTS, *RATIOS):
        raise ValueError('Unsupported weekly matchup tiebreaker')
    if len({w.week for w in weeks}) != len(weeks):
        raise ValueError('Duplicate matchup weeks')
    rng = np.random.default_rng(seed)
    # Ranking coin flips must not change future player-game draws.
    rank_rng = np.random.default_rng(np.random.SeedSequence([seed, 1]))
    n, ids = len(teams), [t['team_id'] for t in teams]
    positions = {team_id: i for i, team_id in enumerate(ids)}
    initial = np.array([[t['wins'], t['losses'], t['ties']] for t in teams], dtype=int)
    if np.any(initial < 0):
        raise ValueError('Negative historical record')
    records = np.broadcast_to(initial, (trials, n, 3)).copy()
    h2h = np.zeros((trials, n, n), dtype=np.int16)
    h2h_games = np.zeros((n, n), dtype=int)
    for left, right, outcome in historical_h2h:
        a, b = positions[left], positions[right]
        if outcome not in {-1, 0, 1} or a == b:
            raise ValueError('Invalid historical matchup')
        h2h[:, a, b] += outcome + 1
        h2h[:, b, a] += 1 - outcome
        h2h_games[a, b] += 1
        h2h_games[b, a] += 1
    rank_counts = np.zeros((n, n), dtype=int)
    direction = np.array([-1 if c in reverse_categories else 1 for c in categories])
    weekly_results = []
    for plan in sorted(weeks, key=lambda w: w.week):
        used = [x for pair in plan.official_pairs for x in pair]
        if len(used) != len(set(used)) or any(x not in positions for x in used):
            raise ValueError(f'Invalid official pairs in week {plan.week}')
        totals = np.zeros((trials, n, len(COMPONENTS)))
        for team_id in ids:
            team_index = positions[team_id]
            actual = plan.actual.get(team_id, {})
            for component, i in INDEX.items():
                value = actual.get(component, 0)
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError('Invalid actual totals')
                totals[:, team_index, i] = value
            for player_id, count in sorted(plan.games.get(team_id, {}).items()):
                if not isinstance(count, int) or count < 0:
                    raise ValueError('Invalid scheduled game count')
                if count:
                    distribution = distributions[player_id]
                    if paired_draws:
                        # Stable player/week streams survive roster and lineup changes.
                        player_rng = np.random.default_rng(np.random.SeedSequence([seed, plan.week, player_id]))
                        draws = player_rng.choice(len(distribution.samples), size=(count, trials), p=distribution.weights).T
                    else:
                        draws = rng.choice(len(distribution.samples), size=(trials, count), p=distribution.weights)
                    totals[:, team_index] += distribution.samples[draws].sum(axis=1)
            for player_id, game in sorted(plan.live_games.get(team_id, {}).items()):
                # A separate stream keeps paired full-game draws stable.
                player_rng = np.random.default_rng(np.random.SeedSequence([seed, plan.week, player_id, 1]))
                totals[:, team_index] += sample_remainder(distributions[player_id], game, trials, player_rng)
        stats = category_arrays(totals, categories) * direction
        tie_stats = category_arrays(totals, [matchup_tie_category])[..., 0] if matchup_tie_category else None
        official = {frozenset(pair) for pair in plan.official_pairs}
        matchups = []
        pairs = [(a, b) for a in range(n) for b in range(a + 1, n)] if all_opponents else [
            (positions[a], positions[b]) for a, b in plan.official_pairs]
        for a, b in pairs:
            comparison = np.sign(stats[:, a] - stats[:, b])
            # Floating point percentage arithmetic only; count totals stay exact.
            comparison[np.isclose(stats[:, a], stats[:, b], rtol=0, atol=1e-12)] = 0
            left_wins = (comparison > 0).sum(axis=1)
            right_wins = (comparison < 0).sum(axis=1)
            outcomes = np.sign(left_wins - right_wins).astype(int)
            if matchup_tie_category:
                tie_direction = -1 if matchup_tie_category in reverse_categories else 1
                tied = outcomes == 0
                outcomes[tied] = np.sign(tie_direction * (tie_stats[tied, a] - tie_stats[tied, b])).astype(int)
            is_official = frozenset((ids[a], ids[b])) in official
            matchups.append({
                'team1_id': ids[a], 'team2_id': ids[b], 'official': is_official,
                'p_win': float(np.mean(outcomes > 0)), 'p_tie': float(np.mean(outcomes == 0)),
                'p_loss': float(np.mean(outcomes < 0)),
                'expected_categories': [float(left_wins.mean()), float(right_wins.mean())],
                'categories': {cat: {'p_win': float(np.mean(comparison[:, k] > 0)),
                                     'p_tie': float(np.mean(comparison[:, k] == 0)),
                                     'p_loss': float(np.mean(comparison[:, k] < 0))}
                               for k, cat in enumerate(categories)},
            })
            if is_official:
                for i, result in ((a, outcomes), (b, -outcomes)):
                    records[:, i, 0] += result > 0
                    records[:, i, 1] += result < 0
                    records[:, i, 2] += result == 0
                h2h[:, a, b] += outcomes + 1
                h2h[:, b, a] += 1 - outcomes
                h2h_games[a, b] += 1
                h2h_games[b, a] += 1
        weekly_results.append({'week': plan.week, 'matchups': matchups,
                               'selected_games': {str(t): sum(plan.games.get(t, {}).values()) for t in ids}})
    games = records.sum(axis=2)
    points = 2 * records[:, :, 0] + records[:, :, 2]
    for trial in range(trials):
        order = rank_trial(points[trial], games[trial], h2h[trial], h2h_games, rank_rng)
        rank_counts[order, np.arange(n)] += 1
    standings = []
    for i, team in enumerate(teams):
        probabilities = rank_counts[i] / trials
        standings.append({**team, 'expected_rank': float(probabilities @ np.arange(1, n + 1)),
                          'p_playoffs': float(probabilities[:playoff_teams].sum()),
                          'rank_probabilities': {str(rank + 1): float(p) for rank, p in enumerate(probabilities)},
                          'expected_record': {key: float(records[:, i, k].mean())
                                              for k, key in enumerate(('wins', 'losses', 'ties'))}})
    standings.sort(key=lambda t: t['expected_rank'])
    return {'engine_version': 'calendar-bootstrap-v2', 'trials': trials, 'seed': seed,
            'categories': list(categories), 'playoff_teams': playoff_teams,
            'matchup_tie_category': matchup_tie_category,
            'standings': standings, 'weeks': weekly_results,
            'max_monte_carlo_standard_error': .5 / math.sqrt(trials),
            'tie_breaker': 'Win percentage; tied-group H2H if equal games; coin flip (single division).',
            'assumptions': [
                ('Fixed projected injury returns, IR activations and required drops from the frozen injury report.'
                 if injury_aware else
                 'Fixed selected rosters, calendar slots and player availability; no injury or transaction draws.'),
                'Independent future player-games sampled as whole historical stat lines with recency weights.',
                'Current-week actual counting totals fixed; percentages recomputed from component totals.',
                'Verified in-progress games add simulated production only for the estimated remaining minutes.',
                'Only official scheduled matchups change standings; other pairs are hypothetical for the same week.',
                'Probabilities are conditional model estimates, not yet calibrated on held-out weeks.',
            ]}
