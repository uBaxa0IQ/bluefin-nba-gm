import importlib
from pathlib import Path
from types import SimpleNamespace
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from core.config import DEFAULT_PERIOD
from web.backend.services.probability_jobs import ProbabilityJobs


@pytest.fixture
def client(tmp_path, monkeypatch):
    from core import feature_flags
    monkeypatch.setattr(feature_flags, 'PROBABILISTIC_ENABLED', True)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'web' / 'backend'))
    router = importlib.import_module('routers.probabilistic')
    meta = SimpleNamespace(league_id=5, year=2027, last_refresh_time=None,
                           get_categories=lambda: ['PTS', 'REB'],
                           get_teams=lambda: [SimpleNamespace(team_id=1)])
    jobs = ProbabilityJobs(tmp_path, lambda meta, params, progress: {'trials': params['trials']})
    monkeypatch.setattr(router, 'probability_jobs', jobs)
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[router.get_league_meta] = lambda: meta
    with TestClient(app) as test_client:
        yield test_client
    jobs.executor.shutdown(wait=True)


def test_submit_poll_and_restore_latest(client):
    assert client.get('/api/probabilistic/latest').json() == {'job': None}
    started = client.post('/api/probabilistic/jobs', json={'trials': 3000})
    assert started.status_code == 200
    job_id = started.json()['job_id']
    for _ in range(100):
        job = client.get('/api/probabilistic/jobs/' + job_id).json()
        if job['status'] != 'running':
            break
        time.sleep(.01)
    assert job['status'] == 'complete'
    assert job['result']['trials'] == 3000
    assert client.get('/api/probabilistic/latest').json()['job']['job_id'] == job_id
    assert client.get('/api/probabilistic/jobs/' + '0' * 32).status_code == 404


def test_disabled_feature_rejects_new_calculations(client, monkeypatch):
    from core import feature_flags
    monkeypatch.setattr(feature_flags, 'PROBABILISTIC_ENABLED', False)
    response = client.post('/api/probabilistic/jobs', json={'trials': 10000})
    assert response.status_code == 503
    assert client.get('/api/probabilistic/latest').json() == {'job': None}


def test_trade_job_is_scoped_separately_and_fixed_to_3000(client, monkeypatch, tmp_path):
    router = importlib.import_module('routers.probabilistic')
    jobs = ProbabilityJobs(tmp_path / 'trade', lambda meta, params, progress: {'before': [], 'after': [], 'trials': params['trials']})
    monkeypatch.setattr(router, 'trade_probability_jobs', jobs)
    monkeypatch.setattr(router, 'trade_snapshots', lambda *args: None)
    body = {'my_team_id': 1, 'their_team_id': 2, 'i_give': ['A'], 'i_receive': ['B']}
    try:
        assert client.post('/api/probabilistic/trade/jobs', json={**body, 'trials': 10000}).status_code == 422
        started = client.post('/api/probabilistic/trade/jobs', json=body)
        assert started.status_code == 200
        job_id = started.json()['job_id']
        jobs.executor.shutdown(wait=True)

        job = client.get('/api/probabilistic/trade/jobs/' + job_id).json()
        assert job['status'] == 'complete'
        assert job['result']['trials'] == 3000
        assert client.get('/api/probabilistic/jobs/' + job_id).status_code == 404
        assert client.get('/api/probabilistic/trade/jobs/' + '0' * 32).status_code == 404
    finally:
        jobs.executor.shutdown(wait=True)


def test_contribution_validates_team_and_uses_separate_job_scope(client, monkeypatch, tmp_path):
    router = importlib.import_module('routers.probabilistic')
    jobs = ProbabilityJobs(tmp_path / 'contribution', lambda meta, params, progress: {'team_id': params['team_id'], 'players': []})
    monkeypatch.setattr(router, 'contribution_jobs', jobs)
    try:
        for body in ({'team_id': 99}, {'team_id': 1, 'trials': 10000},
                     {'team_id': 1, 'custom_rosters': {'99': ['A']}},
                     {'team_id': 1, 'punt_categories': ['UNKNOWN']}):
            assert client.post('/api/probabilistic/contribution/jobs', json=body).status_code == 422
        started = client.post('/api/probabilistic/contribution/jobs', json={'team_id': 1})
        assert started.status_code == 200
        job_id = started.json()['job_id']
        jobs.executor.shutdown(wait=True)
        job = client.get('/api/probabilistic/contribution/jobs/' + job_id).json()
        assert job['status'] == 'complete'
        assert job['result']['team_id'] == 1
        assert client.get('/api/probabilistic/jobs/' + job_id).status_code == 404
    finally:
        jobs.executor.shutdown(wait=True)


@pytest.mark.parametrize('body', [
    {'trials': 30001}, {'trials': 0}, {'period': 'not-a-period'},
    {'simulation_mode': 'invalid'}, {'punt_categories': ['UNKNOWN']},
    {'custom_rosters': {'999': ['Player']}}, {'custom_rosters': {'1': ['Player'] * 31}},
])
def test_invalid_inputs_are_rejected_before_starting_worker(client, body):
    assert client.post('/api/probabilistic/jobs', json=body).status_code == 422
