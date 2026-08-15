"""Deterministic, layout-aware normalization of text-native statement rows."""

import re
import io
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
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
STATEMENT_SIGNALS = ("financial position", "balance sheet", "profit and loss", "income statement", "profit or loss", "cash flow")
MAX_OCR_PAGES = 80
OCR_PAGE_TIMEOUT_SECONDS = 30
FINANCIAL_EXTRACTION_VERSION = "financial-layout-v3-ocr"


@dataclass(frozen=True)
class ExtractedFact:
    taxonomy_key: str
    value: Decimal
    unit: str
    currency: str
    period_end: date
    page_number: int
    source_label: str
    extraction_method: str = "text_layout"
    confidence: Decimal = Decimal("0.900000")
    consolidated: bool = True


@dataclass(frozen=True)
class FinancialPage:
    page_number: int
    text: str


def parse_financial_pdf(content: bytes) -> tuple[list[FinancialPage], str, list[str]]:
    """Use positional text first, then bounded OCR only for sparse/image PDFs."""
    import pdfplumber

    pages: list[FinancialPage] = []
    diagnostics: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(layout=True) or ""
            pages.append(FinancialPage(number, text))
    text_chars = sum(len(page.text.strip()) for page in pages)
    classification = "text_native" if text_chars >= max(500, len(pages) * 100) else "scanned_or_sparse"
    if classification == "scanned_or_sparse":
        diagnostics.append("Sparse/image-only PDF detected after normal extraction; bounded selective OCR started.")
        ocr_pages, ocr_diagnostics = _ocr_financial_pages(content, len(pages))
        diagnostics.extend(ocr_diagnostics)
        if ocr_pages:
            pages = ocr_pages
            classification = "ocr"
    return pages, classification, diagnostics


def _ocr_financial_pages(content: bytes, page_count: int) -> tuple[list[FinancialPage], list[str]]:
    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        return [], ["OCR unavailable: pdftoppm and tesseract executables are required."]
    scanned = min(page_count, MAX_OCR_PAGES)
    selected: list[FinancialPage] = []
    failures = 0
    with tempfile.TemporaryDirectory(prefix="psx-ocr-") as directory:
        pdf_path = f"{directory}/source.pdf"
        with open(pdf_path, "wb") as stream:
            stream.write(content)
        try:
            subprocess.run(
                ["pdftoppm", "-f", "1", "-l", str(scanned), "-r", "150", "-png", pdf_path, f"{directory}/page"],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=max(60, scanned * 3),
            )
        except (OSError, subprocess.SubprocessError):
            return [], ["OCR rendering failed or timed out before page recognition."]

        image_paths = sorted(Path(directory).glob("page-*.png"))

        def recognize(image_path: Path) -> str | None:
            try:
                result = subprocess.run(
                    ["tesseract", str(image_path), "stdout", "-l", "eng", "--psm", "6"],
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=OCR_PAGE_TIMEOUT_SECONDS,
                )
            except (OSError, subprocess.SubprocessError):
                return None
            return result.stdout.strip()

        with ThreadPoolExecutor(max_workers=4) as executor:
            recognized = list(executor.map(recognize, image_paths))
        for page_number, text in enumerate(recognized, start=1):
            if text is None:
                failures += 1
                continue
            lowered = text.lower()
            known_labels = sum(alias in lowered for alias in LABELS)
            if any(signal in lowered for signal in STATEMENT_SIGNALS) or known_labels >= 2:
                selected.append(FinancialPage(page_number, text))
    diagnostics = [f"OCR scanned {scanned} of {page_count} pages and selected {len(selected)} financial-statement pages."]
    if page_count > scanned:
        diagnostics.append(f"OCR page safety limit reached; {page_count - scanned} pages were not scanned.")
    if failures:
        diagnostics.append(f"OCR failed or timed out on {failures} pages.")
    if not selected:
        diagnostics.append("OCR found no sufficiently recognizable financial-statement pages.")
    return selected, diagnostics


def _scale(text: str) -> Decimal | None:
    lowered = text.lower()
    if re.search(r"(?:rs\.?|rupees|pkr)\s*(?:in)?\s*(?:'000|000s|thousand)", lowered): return Decimal("1000")
    if re.search(r"(?:rs\.?|rupees|pkr)\s*(?:in)?\s*(?:million|mn)", lowered): return Decimal("1000000")
    if re.search(r"(?:rs\.?|rupees|pkr)\s*(?:in)?\s*(?:billion|bn)", lowered): return Decimal("1000000000")
    if re.search(r"(?:amounts?\s+in\s+)?(?:rs\.?|rupees|pkr)(?:\s+unless|\s*$)", lowered, re.MULTILINE): return Decimal("1")
    return None


def extract_facts(
    pages: list[object],
    period_end: date,
    *,
    extraction_method: str = "text_layout",
    confidence: Decimal = Decimal("0.900000"),
) -> tuple[list[ExtractedFact], list[str]]:
    facts: list[ExtractedFact] = []
    diagnostics: list[str] = []
    seen: set[tuple[str, date]] = set()
    statement_signals = ("statement of financial position", "balance sheet", "profit and loss", "income statement", "statement of profit or loss", "cash flow statement")
    for page in pages:
        page_number = int(getattr(page, "page_number", 0))
        page_text = str(getattr(page, "text", ""))
        lowered_page = page_text.lower()
        scale = _scale(page_text) or _scale("\n".join(str(getattr(candidate, "text", "")) for candidate in pages[max(0, page_number - 2):page_number + 1]))
        if scale is None and any(alias in lowered_page for alias in LABELS):
            diagnostics.append(f"Page {page_number}: reporting scale unknown; rows were not promoted.")
            continue
        # Known financial row labels plus a dense numeric layout are sufficient
        # when PDF extraction drops the statement heading onto an adjacent page.
        known_labels = sum(alias in lowered_page for alias in LABELS)
        if not any(signal in lowered_page for signal in statement_signals) and known_labels < 2:
            continue
        if scale is None:
            diagnostics.append(f"Page {page_number}: reporting scale unknown; rows were not promoted.")
            continue
        unconsolidated = "unconsolidated" in lowered_page and "consolidated" not in lowered_page.replace("unconsolidated", "")
        for raw_line in page_text.splitlines():
            line = " ".join(raw_line.strip().split())
            lowered = line.lower().rstrip(":")
            label = next((alias for alias in sorted(LABELS, key=len, reverse=True) if lowered == alias or lowered.startswith(f"{alias} ")), None)
            if label is None:
                continue
            suffix = line[len(label):]
            values = NUMBER.findall(suffix)
            if not values:
                continue
            taxonomy = LABELS[label]
            # Comparative financial statements conventionally display current
            # then prior period. We only accept two columns; note-reference
            # integers are discarded when three numeric tokens are present.
            value_tokens = values[-2:] if len(values) >= 2 else values
            try:
                comparative_end = date(period_end.year - 1, period_end.month, period_end.day)
            except ValueError:
                comparative_end = date(period_end.year - 1, period_end.month, 28)
            periods = [period_end, comparative_end] if len(value_tokens) == 2 else [period_end]
            for token, fact_period in zip(value_tokens, periods, strict=True):
                key = (taxonomy, fact_period)
                if key in seen:
                    continue
                negative = token.startswith("(") and token.endswith(")")
                try:
                    value = Decimal(token.strip("()").replace(",", "")) * scale
                except InvalidOperation:
                    continue
                if taxonomy in {"earnings_per_share", "dividend_per_share"}:
                    value /= scale
                facts.append(ExtractedFact(taxonomy, -value if negative else value, "PKR", "PKR", fact_period, page_number, line[:255], extraction_method=extraction_method, confidence=confidence, consolidated=not unconsolidated))
                seen.add(key)
    if not facts:
        diagnostics.append("No sufficiently unambiguous known financial-statement rows were found; facts remain unavailable.")
    # Reconciliation is diagnostic only; it never manufactures a balancing fact.
    latest = {fact.taxonomy_key: fact.value for fact in facts if fact.period_end == period_end}
    if all(key in latest for key in ("assets", "liabilities", "equity")):
        delta = abs(latest["assets"] - latest["liabilities"] - latest["equity"])
        tolerance = max(abs(latest["assets"]) * Decimal("0.03"), Decimal("1"))
        if delta > tolerance:
            diagnostics.append("Assets did not approximately reconcile with liabilities plus equity; retained facts require review.")
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
