import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.macro_catalog import MACRO_SERIES, MACRO_SERIES_BY_KEY
from app.models.workstation import (
    DataQualityIssue,
    MacroObservation,
    MacroSeries,
    MacroSeriesProvider,
)
from app.providers.macro.series import ProviderObservation, ProviderResult, fetch_macro_provider
from app.services.macro_ingestion_service import ensure_macro_catalog, persist_provider_result
from app.services.research_service import macro_releases


def _provider(series_key, prefix):
    return next(
        provider
        for provider in MACRO_SERIES_BY_KEY[series_key].providers
        if provider.key.startswith(prefix)
    )


def test_macro_catalog_has_source_independent_series_and_ordered_fallbacks():
    assert 20 <= len(MACRO_SERIES) <= 30
    assert len({spec.key for spec in MACRO_SERIES}) == len(MACRO_SERIES)
    cpi = MACRO_SERIES_BY_KEY["PK_CPI_YOY"]
    assert [provider.source_name for provider in cpi.providers] == [
        "Pakistan Bureau of Statistics",
        "IMF DataMapper API",
        "World Bank Indicators API",
    ]
    assert [provider.priority for provider in cpi.providers] == [10, 20, 30]
    assert not cpi.providers[0].enabled
    assert not cpi.providers[1].enabled
    assert cpi.providers[2].enabled


def test_world_bank_api_parser(monkeypatch):
    payload = json.dumps(
        [
            {"lastupdated": "2026-07-13"},
            [
                {"date": "2025", "value": 5.6},
                {"date": "2024", "value": None},
                {"date": "2023", "value": "9.1"},
            ],
        ]
    ).encode()
    monkeypatch.setattr(
        "app.providers.macro.series._get",
        lambda *args, **kwargs: (payload, "https://api.worldbank.org/example", "application/json"),
    )
    result = fetch_macro_provider(
        _provider("PK_CPI_YOY", "world_bank:"), date(2020, 1, 1), date(2026, 12, 31)
    )
    assert [(row.effective_date, row.value) for row in result.observations] == [
        (date(2023, 1, 1), Decimal("9.1")),
        (date(2025, 1, 1), Decimal("5.6")),
    ]


def test_fred_csv_and_ecb_sdmx_csv_parsers(monkeypatch):
    fred = b"observation_date,FEDFUNDS\n2026-06-01,4.25\n2026-07-01,.\n"
    ecb = b"KEY,TIME_PERIOD,OBS_VALUE\nEXR,2026-06,1.17\nEXR,2026-07,1.18\n"

    def fake_get(url, **kwargs):
        del kwargs
        if "fred" in url:
            return fred, url, "text/csv"
        return ecb, url, "text/csv"

    monkeypatch.setattr("app.providers.macro.series._get", fake_get)
    fred_result = fetch_macro_provider(
        _provider("US_FED_FUNDS", "fred_csv:"), date(2026, 1, 1), date(2026, 12, 31)
    )
    ecb_result = fetch_macro_provider(
        _provider("ECB_USD_EUR", "ecb:"), date(2026, 1, 1), date(2026, 12, 31)
    )
    assert len(fred_result.observations) == 1
    assert fred_result.observations[0].value == Decimal("4.25")
    assert [row.effective_date for row in ecb_result.observations] == [
        date(2026, 6, 1),
        date(2026, 7, 1),
    ]


def test_fred_api_never_exposes_key_in_provenance(monkeypatch):
    provider = replace(_provider("US_FED_FUNDS", "fred_api:"), enabled=True)
    monkeypatch.setattr(settings, "fred_api_key", "super-secret-test-key")
    payload = b'{"observations":[{"date":"2026-06-01","value":"4.25"}]}'

    def fake_get(url, *, params=None):
        assert params["api_key"] == "super-secret-test-key"
        return payload, f"{url}?api_key=super-secret-test-key", "application/json"

    monkeypatch.setattr("app.providers.macro.series._get", fake_get)
    result = fetch_macro_provider(provider, date(2026, 1, 1), date(2026, 12, 31))
    assert "super-secret-test-key" not in result.url
    assert "api_key" not in result.url


def test_imf_parser_contract_is_available_but_runtime_provider_stays_disabled(monkeypatch):
    provider = replace(_provider("PK_CPI_YOY", "imf:"), enabled=True)
    payload = json.dumps(
        {"values": {"PCPIPCH": {"PAK": {"2024": 12.0, "2025": 5.0}}}}
    ).encode()
    monkeypatch.setattr(
        "app.providers.macro.series._get",
        lambda *args, **kwargs: (payload, "https://www.imf.org/example", "application/json"),
    )
    result = fetch_macro_provider(provider, date(2024, 1, 1), date(2025, 12, 31))
    assert [row.value for row in result.observations] == [Decimal("12.0"), Decimal("5.0")]
    assert not _provider("PK_CPI_YOY", "imf:").enabled


def test_reconciliation_retains_conflicts_and_selects_highest_authority(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "source_artifact_root", str(tmp_path / "artifacts"))
    spec = MACRO_SERIES_BY_KEY["PK_CPI_YOY"]
    now = datetime.now(UTC)
    with SessionLocal() as db:
        ensure_macro_catalog(db)
        db.commit()
        imf = ProviderResult(
            "imf:PAK:PCPIPCH",
            "PCPIPCH",
            "https://www.imf.org/example",
            b'{"imf": 5.0}',
            "application/json",
            "fixture-v1",
            now,
            (ProviderObservation(date(2025, 1, 1), Decimal("5.0")),),
        )
        world_bank = ProviderResult(
            "world_bank:PAK:FP.CPI.TOTL.ZG",
            "FP.CPI.TOTL.ZG",
            "https://api.worldbank.org/example",
            b'{"world_bank": 5.2}',
            "application/json",
            "fixture-v1",
            now,
            (ProviderObservation(date(2025, 1, 1), Decimal("5.2")),),
        )
        assert persist_provider_result(db, spec, world_bank) == 1
        assert persist_provider_result(db, spec, imf) == 1
        db.commit()

        series = db.scalar(select(MacroSeries).where(MacroSeries.key == "PK_CPI_YOY"))
        rows = list(
            db.scalars(
                select(MacroObservation)
                .where(MacroObservation.series_id == series.id)
                .order_by(MacroObservation.value)
            )
        )
        assert len(rows) == 2
        selected = next(row for row in rows if row.is_selected)
        provider = db.get(MacroSeriesProvider, selected.provider_id)
        assert provider.provider_key == "imf:PAK:PCPIPCH"
        assert selected.authority == "official_international"
        assert json.loads(selected.selection_reason)["conflict"] is True
        assert db.scalar(
            select(func.count()).select_from(DataQualityIssue).where(
                DataQualityIssue.rule == "macro_provider_disagreement"
            )
        ) == 1
        releases = macro_releases(db, series.id)
        assert len(releases) == 1
        assert releases[0]["provider"] == "imf:PAK:PCPIPCH"
        assert releases[0]["source"] == "IMF DataMapper API"
        assert releases[0]["source_series_id"] == "PCPIPCH"
        assert releases[0]["selection_reason"]["conflict"] is True


def test_macro_scheduler_is_bounded_and_publishes_only_when_enabled(monkeypatch):
    from app.jobs import macro_scheduler

    monkeypatch.setattr(settings, "macro_ingestion_enabled", True)
    monkeypatch.setattr(settings, "macro_queue_target", 2)
    published = []
    monkeypatch.setattr(
        macro_scheduler.refresh_series,
        "apply_async",
        lambda **kwargs: published.append(kwargs),
    )

    result = macro_scheduler.run_once()

    assert result["queued"] == 2
    assert all(item["queue"] == "macro" for item in published)

def test_pk_net_lending_provider_contract():
    spec = MACRO_SERIES_BY_KEY["PK_NET_LENDING_GDP"]

    assert spec.name == "Pakistan general-government net lending/borrowing"
    assert spec.unit == "percent_gdp"
    assert spec.frequency == "annual"
    assert spec.dimension == "fiscal"

    assert [provider.key for provider in spec.providers] == [
        "imf:PAK:GGXCNL_NGDP",
        "world_bank:PAK:GC.NLD.TOTL.GD.ZS",
    ]

    assert spec.providers[0].enabled is False
    assert spec.providers[1].enabled is True

    assert "PK_CASH_BALANCE_GDP" not in MACRO_SERIES_BY_KEY