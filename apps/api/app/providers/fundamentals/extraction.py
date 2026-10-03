"""Deterministic, layout-aware normalization of text-native statement rows."""

import re
import unicodedata
import io
import logging
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


ALIASES = {
    "revenue": {"revenue", "sales", "turnover"},
    "gross_revenue": {"gross revenue", "gross sales"},
    "net_revenue": {"net revenue", "net sales"},
    "gross_profit": {"gross profit"},
    "ebit": {"operating profit", "profit from operations", "operating income"},
    "net_income": {"profit after taxation", "profit after tax", "net profit", "profit for the year", "profit for the period"},
    "assets": {"total assets"},
    "liabilities": {"total liabilities"},
    "equity": {"total equity", "shareholders equity", "shareholders' equity"},
    "cash": {"cash and cash equivalents", "cash & cash equivalents", "cash and cash equivalents at the end of the year"},
    "debt": {"total debt", "borrowings"},
    "earnings_per_share": {"eps", "earnings per share", "basic earnings per share", "earnings per share - basic and diluted"},
    "dividend_per_share": {"dividend per share", "cash dividend per share"},
}
LABELS = {alias: canonical for canonical, aliases in ALIASES.items() for alias in aliases}
NUMBER = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")
STATEMENT_SIGNALS = ("financial position", "balance sheet", "profit and loss", "income statement", "profit or loss", "cash flow")
MAX_OCR_PAGES = 80
OCR_PAGE_TIMEOUT_SECONDS = 30
FINANCIAL_EXTRACTION_VERSION = "financial-layout-v4-validated-columns"


class _MalformedPdfColorFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not (message.startswith("Cannot set ") and " color because " in message)


logging.getLogger("pdfminer.pdfinterp").addFilter(_MalformedPdfColorFilter())


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
    """Use bounded native Poppler text extraction, then OCR only for sparse PDFs."""
    diagnostics: list[str] = []
    pages = _native_text_pages(content)
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


def _native_text_pages(content: bytes) -> list[FinancialPage]:
    """Extract every page in one native process instead of Python page traversal."""
    if not shutil.which("pdftotext"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return [FinancialPage(number, page.extract_text() or "") for number, page in enumerate(reader.pages, start=1)]
    with tempfile.TemporaryDirectory(prefix="psx-pdf-text-") as directory:
        pdf_path = f"{directory}/source.pdf"
        with open(pdf_path, "wb") as stream:
            stream.write(content)
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", pdf_path, "-"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Native PDF text extraction exceeded 90 seconds") from exc
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ValueError("Native PDF text extraction failed") from exc
    decoded = result.stdout.decode("utf-8", errors="replace")
    page_texts = decoded.split("\f")
    if page_texts and not page_texts[-1].strip():
        page_texts.pop()
    return [FinancialPage(number, text) for number, text in enumerate(page_texts, start=1)]


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
    lowered = unicodedata.normalize("NFKC", text).lower().replace("‘", "\'").replace("’", "\'")
    if re.search(r"(?:rs\.?|rupees|pkr)\s*(?:in)?\s*(?:'000|000s|thousand)", lowered): return Decimal("1000")
    if re.search(r"(?:rs\.?|rupees|pkr)\s*(?:in)?\s*(?:million|mn)", lowered): return Decimal("1000000")
    if re.search(r"(?:rs\.?|rupees|pkr)\s*(?:in)?\s*(?:billion|bn)", lowered): return Decimal("1000000000")
    if re.search(r"(?:amounts?\s+in\s+)?(?:rs\.?|rupees|pkr)(?:\s+unless|\s*$)", lowered, re.MULTILINE): return Decimal("1")
    return None


def resolve_report_period(pages: list[object], fallback: date) -> date:
    """Prefer explicit reporting dates for the catalog year, never posting dates."""
    candidates = []
    for page in pages:
        text = " ".join(str(getattr(page, "text", "")).split())
        for match in re.finditer(r"(?:year|period|quarter)\s+end(?:ed|ing)\s+((?:[A-Za-z]+\s+\d{1,2}|\d{1,2}\s+[A-Za-z]+)[, ]+20\d{2})", text, re.I):
            value = parse_period_end(match.group(1))
            if value and value.year == fallback.year:
                candidates.append(value)
    if not candidates:
        return fallback
    counts = {value: candidates.count(value) for value in set(candidates)}
    best = max(counts.values())
    winners = [value for value, count in counts.items() if count == best]
    return winners[0] if len(winners) == 1 else fallback


def extract_facts(
    pages: list[object], period_end: date, *, extraction_method: str = "text_layout",
    confidence: Decimal = Decimal("0.900000"),
) -> tuple[list[ExtractedFact], list[str]]:
    facts, diagnostics = [], []
    seen = {}
    period_end = resolve_report_period(pages, period_end)
    consolidated = True
    notes_scope = False
    for page in pages:
        page_number = int(getattr(page, "page_number", 0))
        page_text = unicodedata.normalize("NFKC", str(getattr(page, "text", "")))
        heading = " ".join(page_text[:1400].lower().split())
        primary_statement = bool(re.search(r"statement of.{0,30}(?:financial position|profit or loss|cash flows)", heading))
        if primary_statement:
            notes_scope = False
        elif re.search(r"notes to.{0,100}financial statements", heading):
            notes_scope = True
        if re.search(r"(?:party-wise details|name of related party)", page_text, re.I):
            diagnostics.append(f"Page {page_number}: related-party transaction table excluded from company totals.")
            continue
        scale = _scale(page_text)
        columns = None
        calendar_columns = False
        header_dates = None
        month_days = []
        percentage_scope = False
        for raw_line in page_text.splitlines():
            line = " ".join(raw_line.strip().split())
            lowered = line.lower().rstrip(":")
            if re.search(r"analysis.*%", lowered):
                percentage_scope = True
            elif _scale(line) is not None:
                percentage_scope = False
            if len(line) < 160:
                if (re.match(r"^(?:notes to the )?(?:unconsolidated|standalone)\b", lowered)
                    or "financial performance - unconsolidated" in lowered):
                    consolidated = False
                elif (re.match(r"^(?:notes to the )?consolidated\b", lowered)
                      or "performance - consolidated" in lowered
                      or re.search(r"Consolidated Financial Performance\s*$", line)):
                    consolidated = True
            date_labels = re.findall(r"\b([A-Za-z]+\s+\d{1,2}),?", line)
            parsed_days = []
            for text in date_labels:
                try:
                    parsed_days.append(datetime.strptime(text + " 2000", "%B %d %Y"))
                except ValueError:
                    pass
            if len(parsed_days) >= 2:
                month_days = parsed_days
            label = next((alias for alias in sorted(LABELS, key=len, reverse=True)
                          if re.match(re.escape(alias) + r"(?:\s|\*|$)", lowered)), None)
            years = re.findall(r"\b20\d{2}\b", line)
            fiscal = re.findall(r"(?:1H|[369]M|FY)\s*(?:FY)?\s*(20\d{2}|\d{2})(?!\d)", line, re.I)
            if label is None and len(years) >= 2 and all(1900 < int(y) <= period_end.year for y in years):
                columns = [int(y) for y in years]
                calendar_columns = True
                try:
                    header_dates = [date(year, md.month, md.day) for year, md in zip(columns, month_days)] if len(month_days) == len(columns) else None
                except ValueError:
                    header_dates = None
            elif label is None and len(fiscal) >= 2:
                columns = [int(y) if len(y) == 4 else 2000 + int(y) for y in fiscal]
                calendar_columns = False
                header_dates = None
            if label is None or percentage_scope:
                continue
            suffix = line[len(label):]
            # Statement labels must be followed by numeric cells, not prose,
            # volume descriptions, embedded dates or narrative snippets.
            cleaned = re.sub(r"\((?:PKR|Rs\.?|rupees)\)", "", suffix, flags=re.I)
            cleaned = cleaned.replace("*", "")
            if re.search(r"[A-Za-z]", cleaned):
                diagnostics.append(f"Page {page_number}: narrative/ambiguous {LABELS[label]} row not promoted.")
                continue
            tokens = [m.group() for m in NUMBER.finditer(cleaned)
                      if not cleaned[m.end():].lstrip().startswith("%")]
            if not tokens:
                continue
            taxonomy = LABELS[label]
            # A statement explicitly deducting sales tax/excise from "Revenue"
            # identifies that top line as gross, not net revenue.
            if taxonomy == "revenue" and label == "revenue" and primary_statement and re.search(r"less:\s*sales tax", page_text, re.I):
                taxonomy = "gross_revenue"
            if notes_scope and taxonomy != "debt":
                continue
            per_share = taxonomy in {"earnings_per_share", "dividend_per_share"}
            if scale is None and (not per_share or not re.search(r"\b(?:PKR|Rs\.?|rupees)\b", page_text, re.I)):
                diagnostics.append(f"Page {page_number}: reporting scale unknown; {taxonomy} row not promoted.")
                continue
            if columns:
                if len(set(columns)) != len(columns) and (not header_dates or len(set(header_dates)) != len(header_dates)):
                    diagnostics.append(f"Page {page_number}: duplicate-year date columns need explicit dates; {taxonomy} row not promoted.")
                    continue
                # A leading note reference is allowed only in addition to every
                # declared year column, never inferred by taking the last two.
                if len(tokens) == len(columns) + 1 and re.fullmatch(r"\d{1,2}(?:\.\d{1,2})?", tokens[0]):
                    tokens = tokens[1:]
                if len(tokens) != len(columns):
                    diagnostics.append(f"Page {page_number}: ambiguous {taxonomy} columns not promoted.")
                    continue
                anchor = max(columns)
                periods = []
                for index, year in enumerate(columns):
                    mapped_year = year if calendar_columns else period_end.year - (anchor - year)
                    try:
                        periods.append(header_dates[index] if header_dates else period_end.replace(year=mapped_year))
                    except ValueError:
                        periods.append(date(mapped_year, period_end.month, 28))
            else:
                # Preserve the existing simple single/two-column contract.
                # Multi-column rows require explicit header mapping.
                if len(tokens) > 2:
                    diagnostics.append(f"Page {page_number}: missing year header for {taxonomy} row.")
                    continue
                try:
                    prior = period_end.replace(year=period_end.year - 1)
                except ValueError:
                    prior = date(period_end.year - 1, period_end.month, 28)
                periods = [period_end, prior][:len(tokens)]
            for token, fact_period in zip(tokens, periods, strict=True):
                key = (taxonomy, fact_period, consolidated)
                rank = 2 if primary_statement else 1
                if key in seen and seen[key][1] >= rank:
                    continue
                try:
                    amount = Decimal(token.strip("()").replace(",", ""))
                except InvalidOperation:
                    continue
                value = amount * (Decimal(1) if per_share else scale)
                if token.startswith("("):
                    value = -value
                fact = ExtractedFact(taxonomy, value, "PKR", "PKR", fact_period,
                    page_number, line[:255], extraction_method=extraction_method,
                    confidence=confidence, consolidated=consolidated)
                if key in seen:
                    facts[seen[key][0]] = fact
                else:
                    seen[key] = (len(facts), rank)
                    facts.append(fact)
                seen[key] = (seen[key][0], rank)
    if not facts:
        diagnostics.append("No sufficiently unambiguous financial rows were found; facts remain unavailable.")
    for basis in (True, False):
        latest = {fact.taxonomy_key: fact.value for fact in facts
                  if fact.period_end == period_end and fact.consolidated == basis}
        if all(key in latest for key in ("assets", "liabilities", "equity")):
            delta = abs(latest["assets"] - latest["liabilities"] - latest["equity"])
            if delta > max(abs(latest["assets"]) * Decimal("0.03"), Decimal(1)):
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
