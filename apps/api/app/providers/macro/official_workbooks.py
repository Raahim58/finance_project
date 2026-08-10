from dataclasses import dataclass
from datetime import date
from io import BytesIO
import re

import httpx
import pandas as pd


@dataclass(frozen=True)
class MacroObservation:
    series_key: str
    effective_date: date
    value: float
    unit: str
    source: str


class PbsPriceProvider:
    source = "pbs"
    workbook_url = "https://www.pbs.gov.pk/wp-content/uploads/2020/07/SPI-Monthly-Prices-Annex-6.xlsx"
    parser_version = "pbs-spi-monthly-xlsx-v1"
    enabled = True

    @staticmethod
    def parse_items(frame: pd.DataFrame) -> list[MacroObservation]:
        title = str(frame.iloc[0, 0])
        match = re.search(r"month of ([A-Za-z]+) (\d{4})", title)
        if not match:
            raise ValueError("PBS SPI title/date contract changed")
        effective = date(int(match.group(2)), datetime_month(match.group(1)), 1)
        headers = [str(value).strip() for value in frame.iloc[1].tolist()]
        required = {"S. No.", "Description", "Unit"}
        if not required.issubset(headers):
            raise ValueError("PBS SPI item headers changed")
        description_index = headers.index("Description"); unit_index = headers.index("Unit")
        average_candidates = [index for index, value in enumerate(headers) if value.startswith("Average Prices")]
        if not average_candidates:
            raise ValueError("PBS SPI average-price column is missing")
        average_index = average_candidates[0]
        rows = []
        for _, values in frame.iloc[2:].iterrows():
            description = str(values.iloc[description_index]).strip()
            try: value = float(values.iloc[average_index])
            except (TypeError, ValueError): continue
            if description.lower() == "nan": continue
            key = "pbs.spi.item." + re.sub(r"[^a-z0-9]+", "_", description.lower()).strip("_")
            rows.append(MacroObservation(key, effective, value, str(values.iloc[unit_index]).strip(), "pbs"))
        return rows

    def fetch(self) -> list[MacroObservation]:
        response = httpx.get(self.workbook_url, timeout=60, follow_redirects=True, headers={"User-Agent": "psx-ai-portfolio-agent/0.1 (personal research; low-rate ingestion)"})
        response.raise_for_status()
        frame = pd.read_excel(BytesIO(response.content), sheet_name="Items 1-51", header=None)
        return self.parse_items(frame)


class WorldBankCommodityProvider:
    source = "world_bank"
    workbook_url = "https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx"
    parser_version = "world-bank-pink-sheet-monthly-v1"
    enabled = True

    @staticmethod
    def parse_monthly_prices(frame: pd.DataFrame) -> list[MacroObservation]:
        if "World Bank Commodity Price Data" not in str(frame.iloc[0, 0]) or "Updated on" not in str(frame.iloc[3, 0]):
            raise ValueError("World Bank Pink Sheet title contract changed")
        names = frame.iloc[4]; units = frame.iloc[5]
        rows = []
        for _, values in frame.iloc[6:].iterrows():
            match = re.fullmatch(r"(\d{4})M(\d{2})", str(values.iloc[0]))
            if not match: continue
            effective = date(int(match.group(1)), int(match.group(2)), 1)
            for index in range(1, len(values)):
                name = str(names.iloc[index]).strip()
                try: value = float(values.iloc[index])
                except (TypeError, ValueError): continue
                key = "world_bank.commodity." + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
                rows.append(MacroObservation(key, effective, value, str(units.iloc[index]).strip(), "world_bank"))
        return rows

    def fetch(self) -> list[MacroObservation]:
        response = httpx.get(self.workbook_url, timeout=60, follow_redirects=True, headers={"User-Agent": "psx-ai-portfolio-agent/0.1 (personal research; low-rate ingestion)"})
        response.raise_for_status()
        frame = pd.read_excel(BytesIO(response.content), sheet_name="Monthly Prices", header=None)
        return self.parse_monthly_prices(frame)


def datetime_month(name: str) -> int:
    import calendar
    mapping = {month.lower(): index for index, month in enumerate(calendar.month_name) if month}
    if name.lower() not in mapping:
        raise ValueError("Unknown month")
    return mapping[name.lower()]
