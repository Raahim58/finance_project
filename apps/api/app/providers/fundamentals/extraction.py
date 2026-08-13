"""Conservative extraction of normalized facts from text-native financial statements.

Only unambiguous single-value rows with an explicit PKR scale are accepted. Ambiguous
multi-column rows remain in document/RAG storage and are not promoted to exact facts.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


ALIASES = {
    "revenue": {"revenue", "sales", "net sales", "turnover"},
    "gross_profit": {"gross profit"},
    "ebit": {"operating profit", "profit from operations", "operating income"},
    "net_income": {"profit after taxation", "profit after tax", "net profit", "profit for the year", "profit for the period"},
    "assets": {"total assets"},
    "liabilities": {"total liabilities"},
    "equity": {"total equity", "shareholders equity", "shareholders' equity"},
    "cash": {"cash and cash equivalents", "cash & cash equivalents"},
    "debt": {"total debt", "borrowings"},
    "earnings_per_share": {"eps", "earnings per share", "basic earnings per share"},
    "dividend_per_share": {"dividend per share", "cash dividend per share"},
}
LABELS = {alias: canonical for canonical, aliases in ALIASES.items() for alias in aliases}
NUMBER = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")


@dataclass(frozen=True)
class ExtractedFact:
    taxonomy_key: str
    value: Decimal
    unit: str
    currency: str
    period_end: date
    page_number: int
    source_label: str


def _scale(text: str) -> Decimal | None:
    lowered = text.lower()
    if re.search(r"(?:rs\.?|rupees|pkr)\s*(?:in)?\s*(?:'000|000s|thousand)", lowered): return Decimal("1000")
    if re.search(r"(?:rs\.?|rupees|pkr)\s*(?:in)?\s*(?:million|mn)", lowered): return Decimal("1000000")
    if re.search(r"(?:rs\.?|rupees|pkr)\s*(?:in)?\s*(?:billion|bn)", lowered): return Decimal("1000000000")
    if re.search(r"(?:amounts?\s+in\s+)?(?:rs\.?|rupees|pkr)(?:\s+unless|\s*$)", lowered, re.MULTILINE): return Decimal("1")
    return None


def extract_facts(pages: list[object], period_end: date) -> tuple[list[ExtractedFact], list[str]]:
    combined = "\n".join(str(getattr(page, "text", "")) for page in pages)
    scale = _scale(combined)
    if scale is None:
        return [], ["No explicit PKR reporting scale was found; numerical rows were not promoted to structured facts."]
    facts: list[ExtractedFact] = []
    seen: set[str] = set()
    for page in pages:
        page_number = int(getattr(page, "page_number", 0))
        for raw_line in str(getattr(page, "text", "")).splitlines():
            line = " ".join(raw_line.strip().split())
            lowered = line.lower().rstrip(":")
            label = next((alias for alias in sorted(LABELS, key=len, reverse=True) if lowered == alias or lowered.startswith(f"{alias} ")), None)
            if label is None:
                continue
            suffix = line[len(label):]
            values = NUMBER.findall(suffix)
            if len(values) != 1:
                continue
            taxonomy = LABELS[label]
            if taxonomy in seen:
                continue
            token = values[0]
            negative = token.startswith("(") and token.endswith(")")
            try:
                value = Decimal(token.strip("()").replace(",", "")) * scale
            except InvalidOperation:
                continue
            if taxonomy in {"earnings_per_share", "dividend_per_share"}:
                value /= scale
            facts.append(ExtractedFact(taxonomy, -value if negative else value, "PKR", "PKR", period_end, page_number, label))
            seen.add(taxonomy)
    diagnostics = [] if facts else ["No unambiguous single-value known financial rows were found; multi-column rows require a structured parser or review."]
    return facts, diagnostics


def parse_period_end(value: str) -> date | None:
    value = value.strip()
    for pattern, order in ((r"(\d{4})-(\d{1,2})-(\d{1,2})", "ymd"), (r"(\d{1,2})-(\d{1,2})-(\d{4})", "dmy")):
        match = re.search(pattern, value.replace("/", "-"))
        if match:
            parts = [int(item) for item in match.groups()]
            try: return date(parts[0], parts[1], parts[2]) if order == "ymd" else date(parts[2], parts[1], parts[0])
            except ValueError: return None
    normalized = re.sub(r"\s+", " ", value.replace(",", " ")).strip()
    for pattern in ("%d %B %Y", "%B %d %Y", "%d %b %Y", "%b %d %Y"):
        match = re.search(r"\b(?:\d{1,2} [A-Za-z]+ \d{4}|[A-Za-z]+ \d{1,2} \d{4})\b", normalized)
        if match:
            try:
                return datetime.strptime(match.group(0), pattern).date()
            except ValueError:
                continue
    year = re.search(r"\b(20\d{2})\b", value)
    return date(int(year.group(1)), 12, 31) if year else None
