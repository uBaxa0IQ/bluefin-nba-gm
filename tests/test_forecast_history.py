import sqlite3

from web.backend.services.forecast_history import connect, record


def test_forecast_database_migrates_legacy_schema(tmp_path, monkeypatch):
    path = tmp_path / "forecast.db"
    monkeypatch.setenv("FORECAST_DB", str(path))
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE forecasts (league INTEGER, season INTEGER, week INTEGER, team1 INTEGER, team2 INTEGER, period TEXT, categories TEXT, reverse_cats TEXT, prediction TEXT, actual TEXT, created TEXT, PRIMARY KEY(league,season,week,team1,team2,period))")
    with connect() as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(forecasts)")}
    assert {"p_win", "p_tie", "p_loss", "engine_version", "seed", "trials"} <= columns
    record(1, 2030, 2, 1, 2, "total", {"PTS": 10}, {"PTS": 8}, ["PTS"], [], {
        "p_win": .7, "p_tie": .1, "p_loss": .2, "engine_version": "test", "seed": 3, "trials": 100,
    })
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT p_win,engine_version FROM forecasts").fetchone() == (.7, "test")
