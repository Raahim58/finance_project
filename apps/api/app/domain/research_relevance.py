"""Bounded factor matching. Broad event categories never imply factor exposure."""

import hashlib
import json
import re
from datetime import datetime, UTC
from typing import Any

FACTORS = ("oil_price", "pk_policy_rate", "usd_pkr")
VERSION = "research-v1"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def detect_factors(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text.lower())
    found = []
    # Oil discoveries/production are direct operational events, not price shocks.
    if re.search(
        r"\b(?:oil|crude|brent|wti) (?:prices?|futures)\b|\b(?:price of (?:crude )?oil|brent crude prices?|wti crude prices?)\b",
        text,
    ):
        found.append("oil_price")
    if re.search(r"\b(?:sbp|state bank of pakistan|pakistan)\b", text) and re.search(
        r"\b(?:policy rate|monetary policy|discount rate|rate cut|rate hike)\b", text
    ):
        found.append("pk_policy_rate")
    if re.search(r"\b(?:usd[ /-]*pkr|rupee|pkr)\b", text) and re.search(
        r"\b(?:dollar|usd|depreciat\w*|appreciat\w*|exchange rate|devalu\w*)\b", text
    ):
        found.append("usd_pkr")
    return found
