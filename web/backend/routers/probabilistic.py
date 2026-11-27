"""Async API for the calendar-based probabilistic simulation."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from dependencies import get_league_meta
from core.config import DEFAULT_PERIOD, PERIODS, normalize_period
from core import feature_flags
from services.probability_jobs import probability_jobs
from services.trade_probability import trade_probability_jobs, trade_snapshots
from services.roster_contribution import contribution_jobs
from models import TeamTrade

router = APIRouter(prefix='/api/probabilistic', tags=['probabilistic'])


class ProbabilityRequest(BaseModel):
    period: str = DEFAULT_PERIOD
    simulation_mode: Literal['all', 'exclude_ir', 'top_n', 'injury_aware'] = 'top_n'
    top_n_players: int = Field(default=13, ge=1, le=30)
    custom_rosters: dict[int, list[str]] = Field(default_factory=dict)
    punt_categories: list[str] = Field(default_factory=list, max_length=20)
    punt_team_id: int | None = None
    ir_return_drops: dict[int, int] = Field(default_factory=dict)
    trials: int = Field(default=10000, ge=1000, le=30000)
    seed: int = Field(default=20261116, ge=0, le=2**32 - 1)

    @field_validator('period')
    @classmethod
    def validate_period(cls, value):
        value = normalize_period(value)
        if value not in PERIODS.values():
            raise ValueError('Неизвестный период статистики')
        return value

    @field_validator('custom_rosters')
    @classmethod
    def validate_rosters(cls, value):
        if len(value) > 32 or any(len(names) > 30 or any(not name or len(name) > 150 for name in names) for names in value.values()):
            raise ValueError('Неверный состав')
        return {team: sorted(set(names)) for team, names in value.items()}


class TradeProbabilityRequest(ProbabilityRequest):
    my_team_id: int
    their_team_id: int
    i_give: list[str] = Field(min_length=1, max_length=30)
    i_receive: list[str] = Field(min_length=1, max_length=30)
    trials: Literal[3000] = 3000


class TradeScenarioRequest(ProbabilityRequest):
    trades: list[TeamTrade] = Field(min_length=2, max_length=32)
    trials: Literal[3000] = 3000


class ContributionRequest(ProbabilityRequest):
    team_id: int
    trials: Literal[3000] = 3000


@router.post('/contribution/jobs')
def start_contribution(body: ContributionRequest, metadata=Depends(get_league_meta)):
    if not feature_flags.PROBABILISTIC_ENABLED:
        raise HTTPException(503, 'Вероятностный режим временно отключён')
    ids = {team.team_id for team in metadata.get_teams()}
    if body.team_id not in ids or set(body.custom_rosters) - ids or (body.punt_team_id is not None and body.punt_team_id not in ids):
        raise HTTPException(422, 'Неизвестная команда')
    if set(body.punt_categories) - set(metadata.get_categories()):
        raise HTTPException(422, 'Неизвестные пант-категории')
    try:
        return contribution_jobs.submit(metadata, body.model_dump(exclude_none=True))
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from error


@router.get('/contribution/jobs/{job_id}')
def get_contribution(job_id: str, metadata=Depends(get_league_meta)):
    job = contribution_jobs.get(metadata, job_id)
    if not job:
        raise HTTPException(404, 'Расчёт не найден')
    return job


@router.post('/trade/jobs')
def start_trade_probability(body: TradeProbabilityRequest | TradeScenarioRequest, metadata=Depends(get_league_meta)):
    if not feature_flags.PROBABILISTIC_ENABLED:
        raise HTTPException(503, 'Вероятностный режим временно отключён')
    params = body.model_dump(exclude_none=True)
    if body.punt_team_id is not None and body.punt_team_id not in {t.team_id for t in metadata.get_teams()}:
        raise HTTPException(422, 'Неизвестная команда')
    if set(body.punt_categories) - set(metadata.get_categories()):
        raise HTTPException(422, 'Неизвестные пант-категории')
    try:
        trade_snapshots(metadata, params)
        return trade_probability_jobs.submit(metadata, params)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from error


@router.get('/trade/jobs/{job_id}')
def get_trade_probability(job_id: str, metadata=Depends(get_league_meta)):
    job = trade_probability_jobs.get(metadata, job_id)
    if not job:
        raise HTTPException(404, 'Расчёт не найден')
    return job


@router.post('/jobs')
def start_probability_job(body: ProbabilityRequest, metadata=Depends(get_league_meta)):
    if not feature_flags.PROBABILISTIC_ENABLED:
        raise HTTPException(503, 'Вероятностный режим временно отключён')
    if set(body.punt_categories) - set(metadata.get_categories()):
        raise HTTPException(422, 'Неизвестные пант-категории')
    ids = {team.team_id for team in metadata.get_teams()}
    if set(body.custom_rosters) - ids or (body.punt_team_id is not None and body.punt_team_id not in ids):
        raise HTTPException(422, 'Неизвестная команда')
    try:
        return probability_jobs.submit(metadata, body.model_dump(exclude_none=True))
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from error


@router.get('/latest')
def latest_probability_job(metadata=Depends(get_league_meta)):
    return {'job': probability_jobs.latest(metadata)}


@router.get('/jobs/{job_id}')
def get_probability_job(job_id: str, metadata=Depends(get_league_meta)):
    job = probability_jobs.get(metadata, job_id)
    if not job:
        raise HTTPException(404, 'Расчёт не найден')
    return job
