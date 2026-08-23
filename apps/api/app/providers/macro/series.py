"""Bounded provider adapters for canonical macro-series contracts."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

import httpx
import pandas as pd

from app.core.config import settings
from app.ingestion.macro_catalog import MacroProviderSpec
from app.providers.macro.contracts import ProviderObservation, ProviderResult
from app.providers.macro.official_workbooks import WorldBankCommodityProvider
from app.providers.macro.sbp import SbpKeyIndicatorsProvider
from app.providers.macro.pakistan_monthly import (
    fetch_sbp_monthly,
    fetch_sbp_remittances_recent,
)

USER_AGENT = f"psx-ai-portfolio-agent/0.1 ({settings.evidence_contact_email})"
MAX_MACRO_RESPONSE_BYTES = 25 * 1024 * 1024


def _decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _get(url: str, *, params: dict[str, Any] | None = None) -> tuple[bytes, str, str]:
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        with client.stream("GET", url, params=params) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_MACRO_RESPONSE_BYTES:
                    raise ValueError("Macro response exceeded 25 MiB")
                chunks.append(chunk)
            return b"".join(chunks), str(response.url), response.headers.get("content-type", "")


def _date(value: str) -> date:
    value = value.strip()
    if len(value) == 4:
        return date(int(value), 1, 1)
    if len(value) == 7:
        return date.fromisoformat(f"{value}-01")
    return date.fromisoformat(value[:10])


def _world_bank(provider: MacroProviderSpec, start: date, end: date) -> ProviderResult:
    country = str(provider.params["country"])
    url = f"https://api.worldbank.org/v2/country/{country}/indicator/{provider.source_series_id}"
    content, final_url, content_type = _get(
        url,
        params={"format": "json", "per_page": 20000, "date": f"{start.year}:{end.year}"},
    )
    payload = json.loads(content)
    records = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
    observations = []
    for row in records or []:
        value = _decimal(row.get("value"))
        if value is None or not str(row.get("date") or "").isdigit():
            continue
        observations.append(ProviderObservation(date(int(row["date"]), 1, 1), value))
    return ProviderResult(provider.key, provider.source_series_id, final_url, content, content_type, "world-bank-indicators-json-v1", datetime.now(UTC), tuple(sorted(observations, key=lambda item: item.effective_date)))


def _fred_api(provider: MacroProviderSpec, start: date, end: date) -> ProviderResult:
    if not settings.fred_api_key.strip():
        raise RuntimeError("FRED_API_KEY is not configured")
    url = "https://api.stlouisfed.org/fred/series/observations"
    public_params = {
        "series_id": provider.source_series_id,
        "file_type": "json",
        "observation_start": start.isoformat(),
        "observation_end": end.isoformat(),
    }
    try:
        content, _, content_type = _get(
            url,
            params={**public_params, "api_key": settings.fred_api_key},
        )
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"FRED API returned HTTP {exc.response.status_code}") from None
    # Never persist or return the credential-bearing request URL.
    final_url = str(httpx.URL(url).copy_merge_params(public_params))
    payload = json.loads(content)
    observations = []
    for row in payload.get("observations", []):
        value = _decimal(row.get("value"))
        if value is not None:
            observations.append(ProviderObservation(_date(str(row["date"])), value))
    return ProviderResult(provider.key, provider.source_series_id, final_url, content, content_type, "fred-observations-json-v1", datetime.now(UTC), tuple(observations))


def _fred_csv(provider: MacroProviderSpec, start: date, end: date) -> ProviderResult:
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    content, final_url, content_type = _get(
        url,
        params={"id": provider.source_series_id, "cosd": start.isoformat(), "coed": end.isoformat()},
    )
    observations = []
    for row in csv.DictReader(io.StringIO(content.decode("utf-8-sig"))):
        value = _decimal(row.get(provider.source_series_id))
        observed_on = row.get("observation_date") or row.get("DATE")
        if value is not None and observed_on:
            observations.append(ProviderObservation(_date(observed_on), value))
    return ProviderResult(provider.key, provider.source_series_id, final_url, content, content_type, "fredgraph-csv-v1", datetime.now(UTC), tuple(observations))


def _imf(provider: MacroProviderSpec, start: date, end: date) -> ProviderResult:
    country = str(provider.params["country"])
    url = f"https://www.imf.org/external/datamapper/api/v1/{provider.source_series_id}/{country}"
    content, final_url, content_type = _get(url)
    payload = json.loads(content)
    values = payload.get("values", {}).get(provider.source_series_id, {}).get(country, {})
    observations = []
    for year, raw in values.items():
        value = _decimal(raw)
        if value is not None and str(year).isdigit() and start.year <= int(year) <= end.year:
            observations.append(ProviderObservation(date(int(year), 1, 1), value))
    return ProviderResult(provider.key, provider.source_series_id, final_url, content, content_type, "imf-datamapper-json-v1", datetime.now(UTC), tuple(sorted(observations, key=lambda item: item.effective_date)))


def _ecb(provider: MacroProviderSpec, start: date, end: date) -> ProviderResult:
    url = f"https://data-api.ecb.europa.eu/service/data/{provider.source_series_id}"
    content, final_url, content_type = _get(
        url,
        params={"format": "csvdata", "startPeriod": start.isoformat(), "endPeriod": end.isoformat()},
    )
    observations = []
    for row in csv.DictReader(io.StringIO(content.decode("utf-8-sig"))):
        value = _decimal(row.get("OBS_VALUE"))
        period = row.get("TIME_PERIOD")
        if value is not None and period:
            observations.append(ProviderObservation(_date(period), value))
    return ProviderResult(provider.key, provider.source_series_id, final_url, content, content_type, "ecb-sdmx-csv-v1", datetime.now(UTC), tuple(observations))


def _sbp(provider: MacroProviderSpec, start: date, end: date) -> ProviderResult:
    del start, end
    source = SbpKeyIndicatorsProvider()
    content, final_url, content_type = _get(source.page_url)
    parsed = source.parse(content, date.today())
    observations = tuple(
        ProviderObservation(item.effective_date, Decimal(str(item.value)))
        for item in parsed
        if item.series_key == provider.source_series_id
    )
    return ProviderResult(provider.key, provider.source_series_id, final_url, content, content_type or "text/html", source.parser_version, datetime.now(UTC), observations)


def _world_bank_pink(provider: MacroProviderSpec, start: date, end: date) -> ProviderResult:
    source = WorldBankCommodityProvider()
    content, final_url, content_type = _get(source.workbook_url)
    frame = pd.read_excel(BytesIO(content), sheet_name="Monthly Prices", header=None)
    parsed = source.parse_monthly_prices(frame)
    observations = tuple(
        ProviderObservation(item.effective_date, Decimal(str(item.value)))
        for item in parsed
        if item.series_key == provider.source_series_id and start <= item.effective_date <= end
    )
    return ProviderResult(provider.key, provider.source_series_id, final_url, content, content_type, source.parser_version, datetime.now(UTC), observations)


def fetch_macro_provider(provider: MacroProviderSpec, start: date, end: date) -> ProviderResult:
    if not provider.enabled:
        raise RuntimeError(f"Macro provider {provider.key} is disabled")
    handlers = {
        "world_bank_api": _world_bank,
        "fred_api": _fred_api,
        "fred_csv": _fred_csv,
        "imf_datamapper": _imf,
        "ecb_sdmx_csv": _ecb,
        "sbp_key_indicators": _sbp,
        "world_bank_pink": _world_bank_pink,
        "sbp_monthly_workbook": _sbp_monthly,
        "sbp_easydata_remittances": _sbp_remittances,
    }
    handler = handlers.get(provider.kind)
    if handler is None:
        raise RuntimeError(f"Macro provider kind {provider.kind!r} is not implemented")
    result = handler(provider, start, end)
    if not result.observations:
        raise ValueError(f"Macro provider {provider.key} returned no observations")
    return result

def _sbp_monthly(
    provider: MacroProviderSpec,
    start: date,
    end: date,
) -> ProviderResult:
    result = fetch_sbp_monthly(
        provider.source_series_id,
        start,
        end,
    )

    return ProviderResult(
        provider_key=provider.key,
        source_series_id=result.source_series_id,
        url=result.url,
        content=result.content,
        content_type=result.content_type,
        parser_version=result.parser_version,
        retrieved_at=result.retrieved_at,
        observations=result.observations,
    )

def _sbp_remittances(
    provider: MacroProviderSpec,
    start: date,
    end: date,
) -> ProviderResult:
    result = fetch_sbp_remittances_recent(
        start,
        end,
    )

    return ProviderResult(
        provider_key=provider.key,
        source_series_id=provider.source_series_id,
        url=result.url,
        content=result.content,
        content_type=result.content_type,
        parser_version=result.parser_version,
        retrieved_at=result.retrieved_at,
        observations=result.observations,
    )
