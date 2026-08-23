"""Shared result contracts for macro provider adapters.

Keeping these value objects independent from provider implementations prevents
provider modules from importing the dispatch module that imports them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class ProviderObservation:
    effective_date: date
    value: Decimal
    vintage_date: date | None = None


@dataclass(frozen=True)
class ProviderResult:
    provider_key: str
    source_series_id: str
    url: str
    content: bytes
    content_type: str
    parser_version: str
    retrieved_at: datetime
    observations: tuple[ProviderObservation, ...]
