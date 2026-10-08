from datetime import UTC, datetime

from app.jobs import pipeline_scheduler


def test_monitoring_tick_runs_once_per_hour_and_survives_failures(monkeypatch):
    calls = []

    class Db:
        def rollback(self):
            calls.append("rollback")

    def runner(_db):
        calls.append("run")
        return 2

    monkeypatch.setattr("app.jobs.scheduler.run_monitoring_jobs", runner)
    monkeypatch.setattr(pipeline_scheduler, "_last_monitoring_hour", None)
    first = datetime(2026, 10, 8, 10, 5, tzinfo=UTC)
    assert pipeline_scheduler.run_monitoring_tick(Db(), first) == 2
    assert pipeline_scheduler.run_monitoring_tick(Db(), first.replace(minute=40)) == 0
    assert pipeline_scheduler.run_monitoring_tick(Db(), first.replace(hour=11)) == 2

    def boom(_db):
        raise RuntimeError("quant unavailable")

    monkeypatch.setattr("app.jobs.scheduler.run_monitoring_jobs", boom)
    assert pipeline_scheduler.run_monitoring_tick(Db(), first.replace(hour=12)) == 0
    assert calls[-1] == "rollback"
