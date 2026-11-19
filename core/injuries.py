"""The public ESPN injury report shared by Bluefin and roster forecasts."""

from datetime import date, datetime
import re
from threading import Lock
from time import monotonic

import pytz
import requests


NBA_TIMEZONE = pytz.timezone('America/New_York')
INJURY_MODE = 'injury_aware'
_URL = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries'
_lock = Lock()
_cached = None


class InjuryReportUnavailable(Exception):
    pass


def nba_date(value):
    if isinstance(value, datetime):
        # ESPN's Player schedule uses naive datetimes in the server's timezone.
        return value.astimezone(NBA_TIMEZONE).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
    return None


def health_record(item):
    athlete, details = item.get('athlete') or {}, item.get('details') or {}
    player_id = athlete.get('id')
    for link in athlete.get('links', []) if not player_id else []:
        match = re.search(r'/id/(\d+)', link.get('href', ''))
        if match:
            player_id = match[1]
            break
    text = ' '.join(str(item.get(k) or '') for k in ('longComment', 'shortComment')).lower()
    season_out = bool(re.search(r'season[- ]ending|out for (?:the|this) season|miss (?:the )?(?:entire|rest of|remainder of) (?:the )?(?:\d{4}[-/]\d{2,4} )?season|won.t (?:play|return)[^.]*?(?:this|the) season', text))
    return_date = details.get('returnDate')
    day = nba_date(return_date)
    status = (item.get('status') or '').upper()
    return {'player_id': int(player_id) if player_id else None, 'name': athlete.get('displayName'),
            'injury_status': 'DTD' if status in ('DAY-TO-DAY', 'QUESTIONABLE', 'DOUBTFUL') else status or 'UNKNOWN',
            'expected_return_date': return_date, 'out_for_season': season_out,
            'long_term': season_out or bool(day and (day - datetime.now(NBA_TIMEZONE).date()).days >= 30),
            'injury_detail': details.get('type'), 'injury_updated_at': item.get('date')}


def parse_injury_report(data):
    return {'players': [health_record(item) for team in data['injuries'] for item in team.get('injuries', [])],
            'updated_at': data.get('timestamp')}


def load_injury_report():
    global _cached
    with _lock:
        if _cached and monotonic() - _cached[0] < 600:
            return _cached[1]
        try:
            response = requests.get(_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=(5, 20))
            response.raise_for_status()
            report = parse_injury_report(response.json())
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            raise InjuryReportUnavailable('Не удалось получить отчёт ESPN о травмах.') from error
        _cached = (monotonic(), report)
        return report


def projection_injury_report(metadata):
    frozen = getattr(metadata, 'projection_injuries', None)
    return load_injury_report() if frozen is None else frozen
