"""Canonical macro-series registry and ordered provider fallbacks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings


@dataclass(frozen=True)
class MacroProviderSpec:
    key: str
    kind: str
    source_name: str
    base_url: str
    source_series_id: str
    priority: int
    authority: str
    retrieval_method: str
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MacroSeriesSpec:
    key: str
    name: str
    unit: str
    frequency: str
    dimension: str
    providers: tuple[MacroProviderSpec, ...]


def _wb(country: str, indicator: str, priority: int = 30) -> MacroProviderSpec:
    return MacroProviderSpec(
        f"world_bank:{country}:{indicator}",
        "world_bank_api",
        "World Bank Indicators API",
        "https://api.worldbank.org",
        indicator,
        priority,
        "official_international",
        "api_json",
        params={"country": country},
    )


def _imf(country: str, indicator: str, priority: int = 20) -> MacroProviderSpec:
    return MacroProviderSpec(
        f"imf:{country}:{indicator}",
        "imf_datamapper",
        "IMF DataMapper API",
        "https://www.imf.org/external/datamapper/api/v1",
        indicator,
        priority,
        "official_international",
        "api_json",
        False,  # Verified HTTP 403 from this runtime; retain as an ordered contract.
        {"country": country},
    )


def _fred(series_id: str, priority: int = 10) -> tuple[MacroProviderSpec, ...]:
    return (
        MacroProviderSpec(
            f"fred_api:{series_id}",
            "fred_api",
            "Federal Reserve Economic Data",
            "https://api.stlouisfed.org",
            series_id,
            priority,
            "official_aggregator",
            "api_json",
            bool(settings.fred_api_key.strip()),
        ),
        MacroProviderSpec(
            f"fred_csv:{series_id}",
            "fred_csv",
            "Federal Reserve Economic Data",
            "https://fred.stlouisfed.org",
            series_id,
            priority + 1,
            "official_aggregator",
            "csv_download",
        ),
    )


def _sbp(source_series_id: str, priority: int = 10) -> MacroProviderSpec:
    return MacroProviderSpec(
        f"sbp:{source_series_id}",
        "sbp_key_indicators",
        "State Bank of Pakistan",
        "https://www.sbp.org.pk",
        source_series_id,
        priority,
        "national_official",
        "html_table",
    )


def _sbp_unverified(source_series_id: str, priority: int = 10) -> MacroProviderSpec:
    return MacroProviderSpec(
        f"sbp_download:{source_series_id}",
        "unavailable",
        "State Bank of Pakistan",
        "https://www.sbp.org.pk/ecodata/",
        source_series_id,
        priority,
        "national_official",
        "xlsx_download",
        False,
        {"reason": "exact workbook contract not yet fixture-verified"},
    )


def _pbs_unverified(source_series_id: str, priority: int = 10) -> MacroProviderSpec:
    return MacroProviderSpec(
        f"pbs_download:{source_series_id}",
        "unavailable",
        "Pakistan Bureau of Statistics",
        "https://www.pbs.gov.pk",
        source_series_id,
        priority,
        "national_official",
        "xlsx_download",
        False,
        {"reason": "aggregate series workbook contract not yet fixture-verified"},
    )


MACRO_SERIES = (
    MacroSeriesSpec("PK_CPI_YOY", "Pakistan consumer-price inflation", "percent_yoy", "annual", "inflation", (_pbs_unverified("CPI_YOY"), _imf("PAK", "PCPIPCH"), _wb("PAK", "FP.CPI.TOTL.ZG"))),
    MacroSeriesSpec("PK_REAL_GDP_GROWTH", "Pakistan real GDP growth", "percent_yoy", "annual", "growth", (_pbs_unverified("REAL_GDP_GROWTH"), _imf("PAK", "NGDP_RPCH"), _wb("PAK", "NY.GDP.MKTP.KD.ZG"))),
    MacroSeriesSpec("PK_CURRENT_ACCOUNT_GDP", "Pakistan current-account balance", "percent_gdp", "annual", "external", (_sbp_unverified("CURRENT_ACCOUNT_GDP"), _imf("PAK", "BCA_NGDPD"), _wb("PAK", "BN.CAB.XOKA.GD.ZS"))),
    MacroSeriesSpec("PK_USD_PKR", "Pakistan rupees per U.S. dollar", "PKR_per_USD", "mixed", "fx", (_sbp_unverified("USD_PKR"), _imf("PAK", "ENDA"), _wb("PAK", "PA.NUS.FCRF"))),
    MacroSeriesSpec("PK_RESERVES_USD", "Pakistan total reserves", "USD", "annual", "external", (_sbp_unverified("TOTAL_RESERVES_USD"), _wb("PAK", "FI.RES.TOTL.CD"))),
    MacroSeriesSpec("PK_REMITTANCES_USD", "Pakistan personal remittances received", "USD", "annual", "external", (_sbp_unverified("REMITTANCES_USD"), _wb("PAK", "BX.TRF.PWKR.CD.DT"))),
    MacroSeriesSpec("PK_FDI_NET_USD", "Pakistan foreign direct investment net inflows", "USD", "annual", "external", (_sbp_unverified("FDI_NET_USD"), _wb("PAK", "BX.KLT.DINV.CD.WD"))),
    MacroSeriesSpec("PK_POLICY_RATE", "SBP policy rate", "percent", "daily", "rates", (_sbp("sbp.policy_rate"),)),
    MacroSeriesSpec("PK_TBILL_3M", "Pakistan 3-month treasury-bill yield", "percent", "auction", "rates", (_sbp("sbp.tbill.3m_yield"),)),
    MacroSeriesSpec("PK_EXPORTS_USD", "Pakistan exports of goods and services", "USD", "annual", "external", (_sbp_unverified("EXPORTS_USD"), _wb("PAK", "BX.GSR.GNFS.CD"))),
    MacroSeriesSpec("PK_IMPORTS_USD", "Pakistan imports of goods and services", "USD", "annual", "external", (_sbp_unverified("IMPORTS_USD"), _wb("PAK", "BM.GSR.GNFS.CD"))),
    MacroSeriesSpec("PK_UNEMPLOYMENT", "Pakistan unemployment rate", "percent", "annual", "labor", (_pbs_unverified("UNEMPLOYMENT"), _wb("PAK", "SL.UEM.TOTL.ZS"))),
    MacroSeriesSpec("PK_CENTRAL_GOV_DEBT_GDP", "Pakistan central-government debt", "percent_gdp", "annual", "fiscal", (_imf("PAK", "GGXWDG_NGDP"), _wb("PAK", "GC.DOD.TOTL.GD.ZS"))),
    MacroSeriesSpec("PK_CASH_BALANCE_GDP", "Pakistan government cash balance", "percent_gdp", "annual", "fiscal", (_imf("PAK", "GGXCNL_NGDP"), _wb("PAK", "GC.BAL.CASH.GD.ZS"))),
    MacroSeriesSpec("US_CPI_INDEX", "United States consumer price index", "index", "monthly", "inflation", _fred("CPIAUCSL")),
    MacroSeriesSpec("US_FED_FUNDS", "United States effective federal funds rate", "percent", "monthly", "rates", _fred("FEDFUNDS")),
    MacroSeriesSpec("US_10Y_YIELD", "United States 10-year Treasury yield", "percent", "daily", "rates", _fred("DGS10")),
    MacroSeriesSpec("US_UNEMPLOYMENT", "United States unemployment rate", "percent", "monthly", "labor", _fred("UNRATE")),
    MacroSeriesSpec("US_REAL_GDP", "United States real gross domestic product", "billions_chained_USD", "quarterly", "growth", _fred("GDPC1")),
    MacroSeriesSpec("TRADE_WEIGHTED_USD", "Trade-weighted U.S. dollar index", "index", "weekly", "fx", _fred("DTWEXBGS")),
    MacroSeriesSpec("ECB_USD_EUR", "U.S. dollars per euro", "USD_per_EUR", "monthly", "fx", (MacroProviderSpec("ecb:EXR:M.USD.EUR.SP00.A", "ecb_sdmx_csv", "European Central Bank Data Portal", "https://data-api.ecb.europa.eu", "EXR/M.USD.EUR.SP00.A", 10, "official_supranational", "sdmx_csv"),)),
    MacroSeriesSpec("GLOBAL_GDP_GROWTH", "World real GDP growth", "percent_yoy", "annual", "growth", (_wb("WLD", "NY.GDP.MKTP.KD.ZG", 10),)),
    MacroSeriesSpec("GLOBAL_CRUDE_OIL_USD_BBL", "World Bank average crude-oil price", "USD_per_bbl", "monthly", "oil", (MacroProviderSpec("world_bank_pink:crude_oil_average", "world_bank_pink", "World Bank Commodity Markets", "https://thedocs.worldbank.org", "world_bank.commodity.crude_oil_average", 20, "official_international", "xlsx_download"),)),
    MacroSeriesSpec("BRENT_USD_BBL", "Brent crude-oil spot price", "USD_per_bbl", "daily", "oil", _fred("DCOILBRENTEU")),
    MacroSeriesSpec("GLOBAL_UREA_USD_MT", "World Bank urea price", "USD_per_mt", "monthly", "fertilizer", (MacroProviderSpec("world_bank_pink:urea", "world_bank_pink", "World Bank Commodity Markets", "https://thedocs.worldbank.org", "world_bank.commodity.urea", 10, "official_international", "xlsx_download"),)),
    MacroSeriesSpec(
        "HENRY_HUB_USD_MMBTU",
        "Henry Hub natural-gas spot price",
        "USD_per_MMBtu",
        "daily",
        "gas",
        _fred("DHHNGSP")
        + (
            MacroProviderSpec(
                "eia:RNGWHHD",
                "unavailable",
                "U.S. Energy Information Administration",
                "https://api.eia.gov",
                "RNGWHHD",
                10,
                "national_official",
                "api_json",
                False,
                {
                    "reason": (
                        "EIA requires an API key and the v2 Henry Hub route/shape has not "
                        "yet been fixture-verified; the FRED copy remains enabled"
                    )
                },
            ),
        ),
    ),
)

MACRO_SERIES_BY_KEY = {spec.key: spec for spec in MACRO_SERIES}
