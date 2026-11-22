"""Public ESPN game logs with a durable cache for offline Monte Carlo reruns."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from urllib.request import Request, urlopen

import numpy as np

from core.monte_carlo import COMPONENTS, PlayerDistribution


def parse_games(data):
    """Keep complete played regular-season games, never turn DNP into zero games."""
    groups = data.get('seasonTypes', [])
    regular = [g for g in groups if 'regular' in g.get('displayName', '').lower()]
    if not regular:
        regular = [g for g in groups if not any(x in g.get('displayName', '').lower().replace('-', '')
                                                for x in ('preseason', 'postseason', 'playoff', 'all star'))]
    rows = {}
    for group in regular:
        for category in group.get('categories', []):
            for entry in category.get('events', []):
                event_id = str(entry['eventId'])
                event = data.get('events', {}).get(event_id, {})
                raw = dict(zip(data.get('labels', []), entry.get('stats', [])))
                try:
                    minutes = float(raw['MIN'])
                    if entry.get('didNotPlay') or minutes <= 0:
                        continue
                    stats = {k: float(raw[k]) for k in ('PTS', 'REB', 'AST', 'STL', 'BLK', 'TO')}
                    for label, makes, attempts in (('FG', 'FGM', 'FGA'), ('FT', 'FTM', 'FTA'), ('3PT', '3PM', '3PA')):
                        stats[makes], stats[attempts] = map(float, str(raw[label]).split('-'))
                    stats['DD'] = float(sum(stats[k] >= 10 for k in ('PTS', 'REB', 'AST', 'STL', 'BLK')) >= 2)
                    if not all(math.isfinite(v) and v >= 0 and v.is_integer() for v in stats.values()):
                        continue
                    if (stats['FGM'] > stats['FGA'] or stats['FTM'] > stats['FTA'] or
                            stats['3PM'] > stats['3PA'] or stats['3PM'] > stats['FGM'] or
                            stats['3PA'] > stats['FGA'] or
                            stats['PTS'] != 2 * stats['FGM'] + stats['3PM'] + stats['FTM']):
                        continue
                except (KeyError, ValueError, TypeError):
                    continue
                if not event.get('gameDate'):
                    continue
                rows[event_id] = {'event_id': event_id, 'date': event['gameDate'], 'minutes': minutes, 'stats': stats}
    return sorted(rows.values(), key=lambda g: g['date'], reverse=True)


def load_games(player_id, season, cache_dir, *, offline=False):
    path = Path(cache_dir) / str(season) / f'{player_id}.json'
    cached = None
    if path.exists():
        cached = json.loads(path.read_text(encoding='utf-8'))
        if offline or time.time() - cached['fetched_at'] < 6 * 3600:
            return cached['games']
    if offline:
        raise ValueError(f'No cached history for player {player_id}, season {season}')
    url = f'https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{player_id}/gamelog?season={season}'
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=25) as response:
                data = json.load(response)
            games = parse_games(data)
            # An upstream error payload is not an empty player history.
            empty_history = isinstance(data.get('filters'), list) and any(
                f.get('name') == 'league' and f.get('value') == 'nba' for f in data['filters'])
            if 'seasonTypes' not in data and not empty_history:
                raise ValueError(f'Unexpected ESPN log response for {player_id}/{season}')
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps({'fetched_at': time.time(), 'games': games}), encoding='utf-8')
            temp.replace(path)
            return games
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def build_distributions(players, season, cache_dir, *, as_of=None, offline=False,
                        half_life_games=20, max_games=60, min_games=8, workers=6,
                        progress=None, excluded_events=()):
    """Recent full game rows; prior season supplements short current histories."""
    if half_life_games <= 0 or max_games < 1 or min_games < 1:
        raise ValueError('Invalid history sampling settings')
    cutoff = as_of or datetime.now(timezone.utc)
    excluded = set(excluded_events)

    def one(player):
        pid = player['player_id']
        rows = []
        counts = {}
        for year in (season, season - 1):
            games = [g for g in load_games(pid, year, cache_dir, offline=offline)
                     if str(g.get('event_id')) not in excluded
                     and datetime.fromisoformat(g['date'].replace('Z', '+00:00')) <= cutoff]
            counts[str(year)] = len(games)
            rows.extend((g, year) for g in games[:max_games])
            if len(rows) >= min_games:
                break
        if not rows:
            raise ValueError(f"No played games for {player['name']} ({pid}); refusing to invent a distribution")
        rows.sort(key=lambda g: g[0]['date'], reverse=True)
        rows = rows[:max_games]
        weights = [2 ** (-i / half_life_games) * (1 if year == season else .35)
                   for i, (_, year) in enumerate(rows)]
        distribution = PlayerDistribution(
            np.array([[g['stats'][c] for c in COMPONENTS] for g, _ in rows]), np.array(weights))
        coverage = {'player_id': pid, 'name': player['name'], 'games': len(rows),
                    'games_by_season': counts, 'effective_games': float(1 / np.square(distribution.weights).sum()),
                    'used_prior_season': any(y < season for _, y in rows),
                    'latest_game': rows[0][0]['date']}
        return pid, distribution, coverage

    distributions, coverage = {}, []
    unique = {p['player_id']: p for p in players}
    if None in unique:
        raise ValueError('All scheduled players require ESPN player IDs')
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, player) for player in unique.values()]
        for future in as_completed(futures):
            pid, distribution, report = future.result()
            distributions[pid] = distribution
            coverage.append(report)
            if progress:
                progress(len(coverage), len(unique))
    coverage.sort(key=lambda p: p['player_id'])
    return distributions, coverage
