"""Run the calendar Monte Carlo engine, without starting or changing the web app."""
import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import DEFAULT_PERIOD, normalize_period
from core.injuries import INJURY_MODE
from core.monte_carlo import simulate_seasons
from web.backend.services.game_history import build_distributions
from web.backend.services.monte_carlo import prepare_season, save_inputs, load_inputs


def write_reports(output, result):
    output.mkdir(parents=True, exist_ok=True)
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    teams = result['standings']
    with (output / 'rank_probabilities.csv').open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file)
        writer.writerow(['team_id', 'team_name', 'expected_rank', 'p_playoffs'] + [f'p_rank_{r}' for r in range(1, len(teams) + 1)])
        for team in teams:
            writer.writerow([team['team_id'], team['team_name'], team['expected_rank'], team['p_playoffs'], *team['rank_probabilities'].values()])
    names = {t['team_id']: t['team_name'] for t in teams}
    with (output / 'matchup_probabilities.csv').open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file)
        writer.writerow(['week', 'team', 'opponent', 'official', 'p_win', 'p_tie', 'p_loss'])
        for week in result['weeks']:
            for match in week['matchups']:
                a, b = names[match['team1_id']], names[match['team2_id']]
                writer.writerow([week['week'], a, b, match['official'], match['p_win'], match['p_tie'], match['p_loss']])
                writer.writerow([week['week'], b, a, match['official'], match['p_loss'], match['p_tie'], match['p_win']])
    lines = [f"Monte Carlo: {result['trials']:,} seasons; seed {result['seed']}",
             f"As of: {result['metadata']['as_of']}",
             result['assumptions'][0],
             'Whole-game recency-weighted bootstrap; probabilities are not calibrated yet.', '',
             'TEAM | EXPECTED RANK | PLAYOFFS | MOST LIKELY POSITIONS']
    for team in teams:
        likely = sorted(team['rank_probabilities'].items(), key=lambda x: x[1], reverse=True)[:3]
        lines.append(f"{team['team_name']} | {team['expected_rank']:.2f} | {team['p_playoffs']:.1%} | " +
                     ', '.join(f'{rank}: {p:.1%}' for rank, p in likely))
    (output / 'summary.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trials', type=int, default=10000)
    parser.add_argument('--seed', type=int, default=20261116)
    parser.add_argument('--period', default=DEFAULT_PERIOD)
    parser.add_argument('--roster-mode', choices=['top_n', 'all', 'exclude_ir', INJURY_MODE], default='top_n')
    parser.add_argument('--top-n', type=int, default=13)
    parser.add_argument('--rosters', type=Path, help='Optional JSON: team ID -> selected player names')
    parser.add_argument('--punts', default='', help='Comma-separated categories for roster and lineup choices')
    parser.add_argument('--punt-team-id', type=int, help='Apply punts to this team when using injury_aware')
    parser.add_argument('--input', type=Path, help='Frozen inputs.json: no network calls')
    parser.add_argument('--output', type=Path, default=ROOT / '.cache' / 'monte_carlo' / 'latest')
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args(argv)
    if args.trials < 1 or args.trials > 100000 or args.seed < 0 or args.top_n < 1 or not 1 <= args.workers <= 12:
        parser.error('Invalid trials, seed, top-n or worker count')
    started = time.monotonic()
    if args.input:
        prepared, distributions = load_inputs(args.input)
        coverage = prepared.pop('coverage')
        print(f'Loaded frozen inputs: {len(distributions)} player distributions', flush=True)
    else:
        from core.league_metadata import LeagueMetadata
        print('Loading league snapshot and official schedule...', flush=True)
        metadata = LeagueMetadata()
        if not metadata.connect_to_league():
            raise RuntimeError('Could not connect to ESPN')
        custom = {int(t): names for t, names in json.loads(args.rosters.read_text(encoding='utf-8')).items()} if args.rosters else None
        prepared = prepare_season(metadata, normalize_period(args.period), simulation_mode=args.roster_mode,
                                  top_n_players=args.top_n, custom_rosters=custom,
                                  punt_categories=tuple(filter(None, args.punts.split(','))),
                                  punt_team_id=args.punt_team_id)
        print(f"Prepared {len(prepared['teams'])} teams, {len(prepared['weeks'])} weeks, "
              f"{len(prepared['players'])} scheduled players", flush=True)
        def progress(done, total):
            if done % 20 == 0 or done == total:
                print(f'Game logs: {done}/{total}', flush=True)
        distributions, coverage = build_distributions(
            prepared['players'], metadata.year, ROOT / '.cache' / 'monte_carlo' / 'game_logs',
            as_of=datetime.fromisoformat(prepared['metadata']['as_of']), workers=args.workers, progress=progress)
        save_inputs(args.output / 'inputs.json', prepared, distributions, coverage)
    print(f'Simulating {args.trials:,} joint seasons...', flush=True)
    result = simulate_seasons(prepared['teams'], prepared['weeks'], distributions,
                              categories=prepared['categories'], reverse_categories=prepared['reverse_categories'],
                              historical_h2h=prepared['historical_h2h'], playoff_teams=prepared['playoff_teams'],
                              trials=args.trials, seed=args.seed, matchup_tie_category=prepared.get('matchup_tie_category'),
                              injury_aware=prepared['metadata'].get('simulation_mode') == INJURY_MODE)
    result['metadata'] = prepared['metadata']
    result['history_coverage'] = coverage
    result['history_model'] = {'sampling': 'whole_game_weighted_bootstrap', 'half_life_games': 20,
                                'maximum_games': 60, 'prior_season_weight': .35,
                                'prior_season_if_current_games_below': 8}
    result['runtime_seconds'] = round(time.monotonic() - started, 3)
    write_reports(args.output, result)
    print(f"Saved: {args.output.resolve()} ({result['runtime_seconds']:.1f}s)", flush=True)
    return result


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
