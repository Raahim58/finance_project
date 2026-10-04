"""Transparent material-news selection; no model calls or financial fact extraction."""
import re

SECTOR_TERMS = {
    "cement": ("cement", "concrete", "construction demand"),
    "fertilizer": ("fertilizer", "fertiliser", "urea", "ammonia", "potash", "phosphate"),
    "textile": ("cotton", "textile", "yarn", "garment"),
    "energy": ("oil", "crude", "gas", "lng", "coal", "electricity", "power generation"),
    "metals": ("steel", "copper", "aluminium", "aluminum", "iron ore"),
    "technology": ("semiconductor", "chip", "chips", "data center", "data centre", "ai investment", "it exports"),
    "shipping": ("freight", "shipping", "logistics", "supply chain", "port", "ports"),
    "banking": ("bank", "banks", "banking", "credit", "interest rate", "policy rate"),
    "automobile": ("automaker", "automakers", "vehicle sales", "auto financing"),
}
TOPIC_TERMS = {
    "geopolitics": ("sanctions", "tariffs", "export controls", "trade war", "blockade", "hormuz", "red sea", "ceasefire", "invasion", "airstrike"),
    "inflation": ("inflation", "consumer prices"),
    "rates": ("interest rates", "policy rate", "rate cut", "rate hike", "bond yields"),
    "fx": ("currency", "rupee", "pkr", "exchange rate", "dollar"),
    "trade": ("imports", "exports", "export", "import", "trade deficit"),
    "demand": ("demand", "sales", "consumption", "dispatches", "despatches"),
    "supply": ("production", "supply", "capacity", "shortage", "output", "shutdown"),
    "costs": ("costs", "prices", "price", "margins", "fuel", "energy costs"),
    "earnings": ("earnings", "profits", "profit", "revenue", "quarterly results"),
    "investment": ("investment", "financing", "acquisition", "merger", "capital expenditure"),
}
EXCLUDED = re.compile(r"\b(?:spotlight interview|webinar|sponsored|product launch|seed varieties|cryogenic|rtl|transistor|design automation|sports|football|cricket|aircraft crash|ebook|mcp servers?|hardware security|security foundations|llm serving|rethink trust|metal(?:s)? price answer)\b|\bAI\b.*\b(?:answer|pricing data|cost question)\b", re.I)


def matches(text, terms):
    return any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I) for term in terms)


def classify_news(title: str, text: str = "") -> dict:
    content = title + "\n" + text
    sectors = sorted(key for key, terms in SECTOR_TERMS.items() if matches(content, terms))
    topics = sorted(key for key, terms in TOPIC_TERMS.items() if matches(content, terms))
    material = bool(topics and (sectors or set(topics) & {"geopolitics", "inflation", "rates", "fx"}))
    eligible = material and not EXCLUDED.search(title)
    return {"version": "material-news-v1", "eligible": bool(eligible),
            "sectors": sectors, "topics": topics,
            "score": min(1.0, .35 + .08 * len(topics) + .04 * len(sectors)) if eligible else 0.0}
