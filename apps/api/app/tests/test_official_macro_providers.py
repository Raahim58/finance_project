from datetime import date
from pathlib import Path
import pandas as pd

from app.providers.macro.official_workbooks import PbsPriceProvider, WorldBankCommodityProvider


FIXTURES = Path(__file__).parent / "fixtures" / "providers"


def test_pbs_observed_spi_workbook_contract():
    frame = pd.read_csv(FIXTURES / "pbs" / "spi_monthly.sample.csv", header=None)
    rows = PbsPriceProvider.parse_items(frame)
    assert len(rows) == 3
    assert rows[0].series_key == "pbs.spi.item.wheat_flour_bag"
    assert rows[0].effective_date == date(2026, 7, 1)
    assert rows[0].value == 2581.31
    assert rows[0].unit == "20 Kg"


def test_world_bank_observed_pink_sheet_contract():
    frame = pd.read_csv(FIXTURES / "world_bank" / "commodity_monthly.sample.csv", header=None)
    rows = WorldBankCommodityProvider.parse_monthly_prices(frame)
    latest_oil = [row for row in rows if row.series_key == "world_bank.commodity.crude_oil_average"][-1]
    latest_urea = [row for row in rows if row.series_key == "world_bank.commodity.urea"][-1]
    assert latest_oil.effective_date == date(2026, 7, 1)
    assert latest_oil.value == 79.8
    assert latest_oil.unit == "($/bbl)"
    assert latest_urea.value == 170
