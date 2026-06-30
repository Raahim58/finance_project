from abc import ABC, abstractmethod
from datetime import date

from sqlalchemy.orm import Session

from app.services.market_ingestion import generate_mock_market_data


class MarketDataProvider(ABC):
    mode: str
    source: str

    @abstractmethod
    def refresh_latest(self, db: Session) -> dict[str, int]:
        raise NotImplementedError


class MockMarketDataProvider(MarketDataProvider):
    mode = "mock"
    source = "mock"

    def refresh_latest(self, db: Session) -> dict[str, int]:
        return generate_mock_market_data(db, days=365, end_date=date.today())


class DpsMarketDataProvider(MarketDataProvider):
    mode = "dps"
    source = "dps"

    def refresh_latest(self, db: Session) -> dict[str, int]:
        raise NotImplementedError(
            "DPS automatic ingestion adapter is a production/current-data path placeholder and still needs source-specific parsing."
        )


class VendorMarketDataProvider(MarketDataProvider):
    mode = "vendor"
    source = "vendor"

    def refresh_latest(self, db: Session) -> dict[str, int]:
        raise NotImplementedError(
            "Vendor automatic ingestion adapter is a production/current-data path placeholder and still needs vendor credentials and mapping."
        )


def get_market_data_provider(mode: str) -> MarketDataProvider:
    normalized = mode.lower()
    providers: dict[str, MarketDataProvider] = {
        "mock": MockMarketDataProvider(),
        "dps": DpsMarketDataProvider(),
        "vendor": VendorMarketDataProvider(),
    }
    if normalized not in providers:
        raise KeyError(f"Unsupported market data mode: {mode}")
    return providers[normalized]
