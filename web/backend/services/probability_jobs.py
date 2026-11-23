"""One bounded background calculation, with durable results scoped to a league."""
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from threading import Lock
from uuid import uuid4

from core.monte_carlo import simulate_seasons
from core.analytics_cache import analytics_version, digest
from core.injuries import INJURY_MODE, projection_injury_report
from .game_history import build_distributions
from .monte_carlo import prepare_season

ROOT = Path(__file__).resolve().parents[3]
logger = logging.getLogger(__name__)


def run_probability_job(metadata, params, progress):
    progress('calendar', 0, 0)
    prepared = prepare_season(metadata, params['period'], simulation_mode=params['simulation_mode'],
                              top_n_players=params['top_n_players'], custom_rosters=params['custom_rosters'],
                              punt_categories=params['punt_categories'], punt_team_id=params.get('punt_team_id'),
                              include_postseason=True)
    progress('histories', 0, len(prepared['players']))
    distributions, coverage = build_distributions(
        prepared['players'], metadata.year, ROOT / '.cache' / 'monte_carlo' / 'game_logs',
        as_of=datetime.fromisoformat(prepared['metadata']['as_of']),
        excluded_events=prepared['excluded_events'],
        progress=lambda done, total: progress('histories', done, total))
    progress('simulation', 0, params['trials'])
    result = simulate_seasons(prepared['teams'], prepared['weeks'], distributions,
                              categories=prepared['categories'], reverse_categories=prepared['reverse_categories'],
                              historical_h2h=prepared['historical_h2h'], playoff_teams=prepared['playoff_teams'],
                              trials=params['trials'], seed=params['seed'],
                              matchup_tie_category=prepared.get('matchup_tie_category'),
                              injury_aware=params['simulation_mode'] == INJURY_MODE,
                              postseason=prepared.get('postseason'))
    if 'postseason_error' in prepared:
        result['postseason_error'] = prepared['postseason_error']
    result['metadata'] = prepared['metadata']
    result['history_coverage'] = coverage
    return result


class ProbabilityJobs:
    def __init__(self, directory=None, runner=run_probability_job, cache_revision=None):
        self.directory = Path(directory or ROOT / '.cache' / 'probabilistic')
        self.runner = runner
        self.cache_revision = cache_revision
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='probabilistic')
        self.lock = Lock()
        self.jobs = {}
        self.active = None

    @staticmethod
    def scope(metadata):
        return f'{int(metadata.league_id)}-{int(metadata.year)}'

    def _path(self, scope, job_id):
        return self.directory / scope / f'{job_id}.json'

    def _write(self, job):
        path = self._path(job['scope'], job['job_id'])
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(job, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temp.replace(path)

    def _pointer(self, path, job_id):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
        temp.write_text(json.dumps({'job_id': job_id}), encoding='utf-8')
        temp.replace(path)

    def find(self, metadata, signature):
        pointer = self.directory / self.scope(metadata) / 'by_signature' / f'{signature}.json'
        try:
            job = self.get(metadata, json.loads(pointer.read_text(encoding='utf-8'))['job_id'])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return job if job and job['status'] == 'complete' and job['signature'] == signature else None

    def _read(self, scope, job_id):
        if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
            return None
        path = self._path(scope, job_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding='utf-8'))

    def latest(self, metadata):
        scope = self.scope(metadata)
        pointer = self.directory / scope / 'latest.json'
        if not pointer.exists():
            return None
        data = json.loads(pointer.read_text(encoding='utf-8'))
        return self.get(metadata, data['job_id'])

    def get(self, metadata, job_id):
        scope = self.scope(metadata)
        with self.lock:
            job = self.jobs.get(job_id)
            if job and job['scope'] == scope:
                return dict(job)
            job = self._read(scope, job_id)
            if job and job['status'] == 'running':
                job = {**job, 'status': 'failed', 'message': 'Сервер перезапущен. Запустите расчёт ещё раз.'}
            return job

    def submit(self, metadata, params):
        # Refresh swaps league/teams on the original metadata object. Freeze those
        # references before the worker starts so a refresh cannot mix snapshots.
        metadata = copy(metadata)
        scope = self.scope(metadata)
        stamp = getattr(metadata, 'last_refresh_time', None)
        source_version = stamp.isoformat() if hasattr(stamp, 'isoformat') else str(stamp or '')
        injury_aware = params.get('simulation_mode') == INJURY_MODE
        if injury_aware:
            metadata.projection_injuries = projection_injury_report(metadata)
        data_version = analytics_version(metadata, stochastic=True, injury_aware=True) if injury_aware else analytics_version(metadata, stochastic=True)
        signature = digest([scope, data_version, params] + ([self.cache_revision] if self.cache_revision else []))
        cached = self.find(metadata, signature)
        if cached:
            self._pointer(self.directory / scope / 'latest.json', cached['job_id'])
            return cached
        with self.lock:
            for existing in self.jobs.values():
                if existing['signature'] == signature and existing['status'] == 'complete':
                    self._pointer(self.directory / scope / 'latest.json', existing['job_id'])
                    return dict(existing)
            if self.active:
                if self.jobs[self.active]['signature'] == signature:
                    return dict(self.jobs[self.active])
                raise RuntimeError('Другой расчёт уже выполняется. Дождитесь его завершения.')
            job_id = uuid4().hex
            job = {'job_id': job_id, 'scope': scope, 'signature': signature, 'params': params,
                   'source_version': source_version, 'data_version': data_version,
                   'created_at': datetime.now(timezone.utc).isoformat(),
                   'status': 'running', 'stage': 'calendar', 'done': 0, 'total': 0}
            self.jobs[job_id] = job
            self.active = job_id
            self._write(job)
            self.executor.submit(self._work, metadata, job_id)
            return dict(job)

    def _work(self, metadata, job_id):
        def progress(stage, done, total, result=None):
            with self.lock:
                self.jobs[job_id].update(stage=stage, done=done, total=total)
                if result is not None:
                    self.jobs[job_id]['result'] = result
        try:
            result = self.runner(metadata, self.jobs[job_id]['params'], progress)
            with self.lock:
                job = self.jobs[job_id]
                job.update(status='complete', stage='complete', result=result,
                           finished_at=datetime.now(timezone.utc).isoformat())
                self._write(job)
                self._pointer(self.directory / job['scope'] / 'latest.json', job_id)
                self._pointer(self.directory / job['scope'] / 'by_signature' / f"{job['signature']}.json", job_id)
        except Exception as error:
            logger.exception('Probabilistic job failed')
            message = 'Не удалось выполнить расчёт. Попробуйте ещё раз.'
            if isinstance(error, ValueError):
                message = str(error)
                if 'shot components missing' in message:
                    message = 'ESPN ещё не отдал попадания и попытки текущей недели. Повторите расчёт после обновления данных.'
            with self.lock:
                self.jobs[job_id].update(status='failed', message=message)
                self._write(self.jobs[job_id])
        finally:
            with self.lock:
                self.active = None
                # Keep the current job and recent results; older ones remain on disk.
                while len(self.jobs) > 4:
                    del self.jobs[next(iter(self.jobs))]


probability_jobs = ProbabilityJobs(cache_revision='postseason-v2')
