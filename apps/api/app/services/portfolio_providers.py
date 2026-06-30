from abc import ABC, abstractmethod

from app.models.portfolio import Portfolio


class PortfolioProvider(ABC):
    name: str
    source_mode: str

    @abstractmethod
    def supports_sync(self) -> bool:
        raise NotImplementedError


class ManualPortfolioProvider(PortfolioProvider):
    name = "ManualPortfolioProvider"
    source_mode = "manual"

    def supports_sync(self) -> bool:
        return False


class MockBrokerPortfolioProvider(PortfolioProvider):
    name = "MockBrokerPortfolioProvider"
    source_mode = "synced"

    def supports_sync(self) -> bool:
        return True


class ExternalBrokerPortfolioProvider(PortfolioProvider):
    name = "ExternalBrokerPortfolioProvider"
    source_mode = "synced"

    def supports_sync(self) -> bool:
        return True


def get_portfolio_provider(source_mode: str, provider_name: str) -> PortfolioProvider:
    provider_map: dict[str, PortfolioProvider] = {
        "ManualPortfolioProvider": ManualPortfolioProvider(),
        "MockBrokerPortfolioProvider": MockBrokerPortfolioProvider(),
        "ExternalBrokerPortfolioProvider": ExternalBrokerPortfolioProvider(),
    }
    provider = provider_map.get(provider_name)
    if provider is None:
        provider = ManualPortfolioProvider() if source_mode == "manual" else ExternalBrokerPortfolioProvider()
    return provider


def describe_portfolio_source(portfolio: Portfolio) -> tuple[str, str]:
    provider = get_portfolio_provider(portfolio.source_mode, portfolio.provider_name)
    return provider.source_mode, provider.name
