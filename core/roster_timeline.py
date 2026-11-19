"""Projected IR activations and corresponding roster moves for one ESPN snapshot."""

from dataclasses import dataclass
from datetime import date
import math

from .injuries import nba_date, projection_injury_report
from .projection import roster_available_on
from .roster_rules import league_slots


def overall_z(player, punts=()):
    return sum(value for category, value in (player.get('z_scores') or {}).items()
               if category not in punts and isinstance(value, (int, float)) and math.isfinite(value))


def is_ir(player):
    return str(player.get('lineup_slot') or '').upper() in {'IR', 'IL'}


def _status(value):
    return str(value or '').upper().replace('-', '_').replace(' ', '_')


@dataclass(frozen=True)
class InjuryContext:
    as_of: date
    roster_limit: int
    injuries: dict
    updated_at: str | None = None
    punt_team_id: int | None = None
    punt_categories: frozenset[str] = frozenset()

    @classmethod
    def from_league(cls, metadata, snapshot, *, punt_team_id=None, punt_categories=()):
        report = projection_injury_report(metadata)
        by_id = {}
        for row in sorted(report['players'], key=lambda row: row.get('injury_updated_at') or ''):
            if row.get('player_id') is not None:
                by_id[row['player_id']] = row
        return cls(nba_date(snapshot.created_at), len(league_slots(metadata, include_bench=True)),
                   by_id, report.get('updated_at'), punt_team_id, frozenset(punt_categories))

    def punts_for(self, team_id):
        return self.punt_categories if team_id is not None and team_id == self.punt_team_id else ()

    def plan(self, players, team_id=None):
        """Resolve dated eligibility once, before selecting lineups or sampling stats."""
        punts = self.punts_for(team_id)
        rows, regular, activations, returns, events, unavailable = [], [], [], [], [], []
        for player in players:
            row = {**player, 'available': True}
            rows.append(row)
            health = self.injuries.get(player.get('player_id'), {})
            status = _status(health.get('injury_status'))
            if status in {'', 'UNKNOWN'}:
                status = _status(player.get('injury_status'))
            expected = nba_date(health.get('expected_return_date') or player.get('expected_return_date'))
            ir = is_ir(player)
            if not ir:
                regular.append(row)
            if health.get('out_for_season') or status in {'OUT', 'INJURY_RESERVE', 'OFS', 'SUSPENSION', 'SUSPENDED'} or ir:
                season_out = health.get('out_for_season') or status == 'OFS'
                if ir and status in {'ACTIVE', 'HEALTHY', 'PROBABLE'} and not season_out:
                    expected = self.as_of
                if season_out or expected is None or expected < self.as_of:
                    row['available'] = False
                    unavailable.append({'player_id': player.get('player_id'), 'name': player['name'],
                                        'status': status, 'in_ir': ir, 'out_for_season': bool(season_out),
                                        'expected_return_date': expected.isoformat() if expected else None})
                elif ir:
                    row['available'] = False
                    activations.append((expected, row))
                else:
                    row['available_from'] = expected
                    returns.append((expected, row))

        def drop_on(day):
            # A return earlier on this same day occupies its slot for the day.
            candidates = [p for p in regular if p.get('droppable', True) and p.get('activated_on') != day]
            if not candidates:
                return None
            dropped = min(candidates, key=lambda p: (overall_z(p, punts), p['name']))
            regular.remove(dropped)
            dropped['available_until'] = day
            return dropped

        # An unequal hypothetical trade can start with more than the league limit.
        while len(regular) > self.roster_limit:
            dropped = drop_on(self.as_of)
            if dropped is None:
                raise ValueError('Невозможно соблюсти лимит состава: все игроки защищены от дропа.')
            events.append({'date': self.as_of.isoformat(), 'kind': 'roster_limit_drop', 'dropped': dropped['name'],
                           'dropped_z': overall_z(dropped, punts)})

        for day, player in sorted(activations, key=lambda pair: (pair[0], -overall_z(pair[1], punts), pair[1]['name'])):
            dropped = None
            if len(regular) >= self.roster_limit:
                dropped = drop_on(day)
                if dropped is None:
                    events.append({'date': day.isoformat(), 'kind': 'activation_blocked', 'player': player['name']})
                    continue
            player.update(available=True, available_from=day, activated_on=day)
            regular.append(player)
            events.append({'date': day.isoformat(), 'kind': 'activate_ir', 'player': player['name'],
                           'dropped': dropped['name'] if dropped else None,
                           'dropped_z': overall_z(dropped, punts) if dropped else None})

        events.extend({'date': day.isoformat(), 'kind': 'return', 'player': player['name']}
                      for day, player in returns if roster_available_on(player, day))
        return rows, {'events': sorted(events, key=lambda e: e['date']), 'unavailable': unavailable}

    def available_today(self, players, team_id=None):
        planned, _ = self.plan(players, team_id)
        return [p for p in planned if roster_available_on(p, self.as_of)]
