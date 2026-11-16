from datetime import datetime, timezone
from threading import Event
import time
from types import SimpleNamespace

import pytest

from web.backend.services.probability_jobs import ProbabilityJobs


def metadata(league=123):
    return SimpleNamespace(league_id=league, year=2027,
                           last_refresh_time=datetime(2026, 11, 16, tzinfo=timezone.utc))


def wait_complete(store, meta, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = store.get(meta, job_id)
        if job['status'] != 'running':
            return job
        time.sleep(.01)
    raise AssertionError('Background job did not finish')


def test_background_progress_deduplication_and_single_job_limit(tmp_path):
    release = Event()
    def runner(meta, params, progress):
        progress('histories', 3, 10)
        assert release.wait(3)
        return {'trials': params['trials']}
    store = ProbabilityJobs(tmp_path, runner)
    try:
        meta = metadata()
        first = store.submit(meta, {'trials': 3000})
        duplicate = store.submit(meta, {'trials': 3000})
        assert duplicate['job_id'] == first['job_id']
        with pytest.raises(RuntimeError):
            store.submit(meta, {'trials': 10000})
        assert store.get(metadata(999), first['job_id']) is None
        release.set()
        complete = wait_complete(store, meta, first['job_id'])
        assert complete['result']['trials'] == 3000
        assert store.latest(meta)['job_id'] == first['job_id']
        assert store.submit(meta, {'trials': 3000})['job_id'] == first['job_id']
    finally:
        release.set()
        store.executor.shutdown(wait=True)


def test_persisted_results_survive_server_restart(tmp_path):
    meta = metadata()
    original = ProbabilityJobs(tmp_path, lambda *args: {'standings': [{'p_playoffs': .75}]})
    try:
        job = original.submit(meta, {'trials': 3000})
        assert wait_complete(original, meta, job['job_id'])['status'] == 'complete'
    finally:
        original.executor.shutdown(wait=True)
    restarted = ProbabilityJobs(tmp_path)
    try:
        latest = restarted.latest(meta)
        assert latest['result']['standings'][0]['p_playoffs'] == .75
        assert restarted.get(meta, '../../other') is None
        assert restarted.latest(metadata(999)) is None
    finally:
        restarted.executor.shutdown(wait=True)


def test_failed_recalculation_preserves_last_good_result(tmp_path):
    calls = []
    def runner(meta, params, progress):
        calls.append(params)
        if params['trials'] == 10000:
            raise ValueError('Missing player history')
        return {'trials': params['trials']}
    meta = metadata()
    store = ProbabilityJobs(tmp_path, runner)
    try:
        first = store.submit(meta, {'trials': 3000})
        assert wait_complete(store, meta, first['job_id'])['status'] == 'complete'
        second = store.submit(meta, {'trials': 10000})
        failed = wait_complete(store, meta, second['job_id'])
        assert failed['status'] == 'failed'
        assert failed['message'] == 'Missing player history'
        assert store.latest(meta)['job_id'] == first['job_id']
    finally:
        store.executor.shutdown(wait=True)


def test_interrupted_job_does_not_poll_forever_after_restart(tmp_path):
    release = Event()
    def runner(*args):
        release.wait(3)
        return {}
    original = ProbabilityJobs(tmp_path, runner)
    restarted = ProbabilityJobs(tmp_path)
    try:
        meta = metadata()
        job = original.submit(meta, {'trials': 3000})
        restored = restarted.get(meta, job['job_id'])
        assert restored['status'] == 'failed'
        assert 'перезапущен' in restored['message']
    finally:
        release.set()
        original.executor.shutdown(wait=True)
        restarted.executor.shutdown(wait=True)
