"""Advance the ESPN championship, placement and consolation brackets."""
from dataclasses import dataclass

import numpy as np

from .monte_carlo import WeekPlan, category_arrays, compare_category_trials, sample_week_totals


@dataclass(frozen=True)
class PlayoffRound:
    plan: WeekPlan
    start: str
    end: str
    # (bracket, team IDs, official winner ID if already decided).
    official: tuple[tuple[str, int, int, int | None], ...] = ()


@dataclass(frozen=True)
class Postseason:
    rounds: tuple[PlayoffRound, ...]
    seeds: tuple[int, ...] = ()
    tie_category: str | None = None


def _next_ladder(winners, losers):
    if len(winners) <= 1:
        return list(zip(winners, losers))
    return list(zip([winners[0], *losers[:-1]], [*winners[1:], losers[-1]]))


def simulate_playoffs(ids, orders, postseason, distributions, categories, reverse_categories, seed):
    trials, count = orders.shape
    positions = {team_id: i for i, team_id in enumerate(ids)}
    seed_index = np.argsort(orders, axis=1)
    samples = np.arange(trials)
    title = [(orders[:, i], orders[:, j]) for i, j in ((0, 7), (3, 4), (2, 5), (1, 6))]
    placement = []
    consolation = [(orders[:, i], orders[:, i+1]) for i in range(8, count, 2)]
    reached = [np.bincount(orders[:, :8].ravel(), minlength=count)]
    finishing = np.zeros((trials, count), dtype=int)
    details = []
    direction = [-1 if cat in reverse_categories else 1 for cat in categories]
    rng = np.random.default_rng(seed)
    for number, round_ in enumerate(postseason.rounds):
        totals = sample_week_totals(round_.plan, ids, distributions, trials, seed, rng, True)
        stats = category_arrays(totals, categories) * direction
        tie = None
        if postseason.tie_category:
            tie = category_arrays(totals, [postseason.tie_category])[..., 0]
            if postseason.tie_category in reverse_categories:
                tie = -tie

        def play(bracket, pairs):
            encounters = np.zeros((count, count), dtype=int)
            wins = np.zeros_like(encounters)
            pairs_official = [(positions[a], positions[b], winner)
                              for kind, a, b, winner in round_.official if kind == bracket]
            entrants = ([(np.full(trials, a), np.full(trials, b), winner) for a, b, winner in pairs_official]
                        if pairs_official else [(a, b, None) for a, b in pairs])
            winners, losers = [], []
            for a, b, winner in entrants:
                if winner is not None:
                    left = a == positions[winner]
                else:
                    _, _, _, outcome = compare_category_trials(
                        stats[samples, a], stats[samples, b],
                        tie[samples, a] if tie is not None else None,
                        tie[samples, b] if tie is not None else None,
                    )
                    left = (outcome > 0) | ((outcome == 0) & (seed_index[samples, a] < seed_index[samples, b]))
                w, l = np.where(left, a, b), np.where(left, b, a)
                winners.append(w)
                losers.append(l)
                np.add.at(encounters, (a, b), 1)
                np.add.at(encounters, (b, a), 1)
                np.add.at(wins, (w, l), 1)
            return winners, losers, [
                {'team_id': ids[a], 'opponent_id': ids[b], 'p_meet': encounters[a, b] / trials,
                 'p_win': wins[a, b] / encounters[a, b], 'bracket': bracket}
                for a, b in zip(*encounters.nonzero())
            ]

        tw, tl, title_matches = play('championship', title)
        pw, pl, placement_matches = play('placement', placement)
        cw, cl, consolation_matches = play('consolation', consolation)
        reached.append(np.bincount(np.concatenate(tw), minlength=count))
        details.append({'week': round_.plan.week, 'start': round_.start, 'end': round_.end,
                        'matchups': title_matches + placement_matches + consolation_matches})
        if number == 0:
            title = [(tw[0], tw[1]), (tw[2], tw[3])]
            # ESPN pairs the four eliminated teams by their original seed.
            eliminated = np.stack(tl, axis=1)
            eliminated = np.take_along_axis(eliminated, np.argsort(seed_index[samples[:, None], eliminated], axis=1), axis=1)
            placement = [(eliminated[:, 0], eliminated[:, 1]), (eliminated[:, 2], eliminated[:, 3])]
        elif number == 1:
            title = [(tw[0], tw[1])]
            placement = [(tl[0], tl[1]), (pw[0], pw[1]), (pl[0], pl[1])]
        else:
            order = [tw[0], tl[0], *[v for pair in zip(pw, pl) for v in pair],
                     *[v for pair in zip(cw, cl) for v in pair]]
            for rank, team in enumerate(order, 1):
                finishing[samples, team] = rank
        consolation = _next_ladder(cw, cl)
    return {
        'rounds': details,
        'official_seeds': {str(t): seed+1 for seed, t in enumerate(postseason.seeds)},
        'teams': [
            {'team_id': tid, 'p_playoffs': reached[0][i] / trials, 'p_semifinal': reached[1][i] / trials,
             'p_final': reached[2][i] / trials, 'p_title': reached[3][i] / trials,
             'p_title_given_playoffs': reached[3][i] / reached[0][i] if reached[0][i] else None,
             'finish_probabilities': {str(rank): float(np.mean(finishing[:, i] == rank))
                                      for rank in range(1, count+1)}}
            for i, tid in enumerate(ids)
        ],
    }
