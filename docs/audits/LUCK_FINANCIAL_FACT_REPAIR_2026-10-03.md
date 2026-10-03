# Targeted LUCK financial-fact correction — 2026-10-03

Scope: source/value verification, confirmed parser/mapping corrections, three-report reprocessing and comparable-period checks only. No pipeline rebuild, model calls, ingestion workers or other Assistant fixes. The user subsequently authorized committing/pushing this existing fix, deploying it to Oracle and activating only the three-report LUCK repair.

## Source findings

Read the live `financial_facts`, document metadata and indexed report pages. FY2024 was not indexed, so fetched its existing report artifact and parsed it with native PDF text extraction. No model was used. Reviewed the statement/table rows against their persisted facts.

| Report | Official source | Reviewed PDF pages (physical PDF page numbering) |
|---|---|---|
| FY2025 | [PSX filing](https://financials.psx.com.pk/lib/DownloadPDF.php?id=258917) | 143, 146, 162–164, 241, 243, 291–294, 363 |
| FY2024 | [PSX filing](https://financials.psx.com.pk/lib/DownloadPDF.php?id=236386) | 138, 141, 158–160, 239, 241, 287–290, 364 |
| Half year ended December 31, 2024 | [PSX filing](https://financials.psx.com.pk/lib/DownloadPDF.php?id=248070) | 7, 16, 29 |

The manifest records exact document IDs, source URLs, source content hashes, original-row fingerprints, replacement values, period boundaries, basis, page numbers and source labels. It is executable repair input, not an instruction to rerun all ingestion.

Confirmed errors:

- Rows with `current / previous / change %` were parsed by taking the last two numbers, consuming growth percentages and shifting current/prior values. FY2025 consolidated EPS should be 52.53 / 44.10, not 44.10 / 19.1. The FY2024 comparison in this filing is restated after the stock split; use the latest filing's comparative rather than the older unadjusted EPS.
- Narrative revenue/volume/subsidiary passages were incorrectly promoted as company totals. FY2025 revenue 14.3 was a growth percentage, not currency revenue.
- `PKR in ‘000’` missed the scale because of curly apostrophes. FY2025 total consolidated debt is PKR 191,504,104,000, not 191,504,104.
- Annual report catalog years mapped to December 31 despite explicit June 30 year-end statements.
- Ascending six-year tables swapped periods; standalone tables were tagged consolidated. The two reporting bases must remain separate.
- Quarterly balance sheets use December 31 / June 30 columns within the same calendar year. Half-year and quarter income columns share end dates but differ in duration; ambiguous multi-duration rows are rejected.
- Joint-venture cash figures in report notes were treated as total group cash. Verified closing cash comes from the company cash-flow statement.
- Gross revenue and net revenue must be distinct. Explicit tax-deduction statements identify the gross top line; margins use net revenue.

## Implementation

`providers/fundamentals/extraction.py`: normalize Unicode, match explicit fiscal dates and column headers, ignore percentage columns, reject narrative/related-party tables, restrict notes to total debt, retain reporting basis, prefer primary statements, parse integer/decimal note references, recognize closing cash and explicit EPS labels. Unknown scales/ambiguous columns remain unavailable; no inferred replacement amounts.

Both existing fact persistence paths retain provenance/basis and allow consolidated and standalone facts for the same metric/date/document.

`research_service.py`: reject confidence-zero rows; deduplicate by period start as well as end/basis/unit; prefer consolidated current observations and the latest version/filing within that basis; growth requires an earlier aligned end date, matching units/basis/type/duration. Unknown interim duration does not qualify. Margins require matching durations; returns on assets/equity use compatible period-end balance inputs and retain their existing unaveraged warning. Expose basis and period start.

`context_builder.py`: filter rejected facts before the row limit, retain period start/basis, include confidence in cache dependencies so repairs invalidate existing fact context. `research_intelligence_service.py` and completeness counts use the same rejection filter. No background-generation changes.

`financial_fact_repair.py`: bounded, reviewed manifest transaction. Validate document hashes and all original-row fingerprints before mutation. Retain original values/provenance; mark superseded/rejected originals with confidence zero and an audit reason, insert versioned source-backed replacements. A repeated application is a no-op; drift or a partial prior repair aborts. No financial fact is deleted.

## Isolated reprocessing result

Loaded the exported 117-row live snapshot into an isolated SQLite database with document metadata, then applied the reviewed manifest and repeated it:

- 3 documents / 51 original rows excluded from use, retained for audit.
- 82 replacement rows, including separately identified net/gross revenue and reporting bases, current and comparative periods only.
- 66 rows from the other four reports unchanged, verified by full-row fingerprints.
- Repeat application: zero inserts and zero changes.
- FY2025 consolidated EPS 52.53 / restated FY2024 44.10; consolidated net revenue PKR 449,629,947,000 / 410,995,183,000. These support a 9.4003% net-revenue change using matching periods/basis.

Verification: 96 tests passed across extraction, repair, ingestion, research, canonical context and data-health suites. One existing event-publisher fixture fails (`test_company_research_exposes_normalized_event_publishers`); reproduced the same failure in a temporary archive of unchanged HEAD, without this patch. It was not changed. `git diff --check` passed.

At completion of the isolated audit, Oracle had not been repaired: its old readers ignored confidence zero. Deployment and LUCK repair activation are now authorized, in that order. Applying this versioned repair before deploying the matching readers would expose superseded and corrected rows together. Deployment/activation results are recorded below after verification.

## Commands

No dependencies or schema migration added. For a fresh API environment:

```sh
cd apps/api
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

Tests in an isolated in-memory database:

```sh
cd apps/api
DATABASE_URL='sqlite+pysqlite:///:memory:' EMBEDDING_BACKEND=hash .venv/bin/python -m pytest app/tests/test_financial_fact_quality.py app/tests/test_fundamentals_extraction.py app/tests/test_phase2_ingestion_plane.py app/tests/test_research_intelligence.py app/tests/test_phase7a_canonical_context.py app/tests/test_phase7b_context_consumers.py app/tests/test_data_health.py -q
```

After deploying this exact code with the existing database configuration, review transaction (always rolls back):

```sh
cd apps/api
.venv/bin/python scripts/apply_financial_fact_repair.py ../../docs/audits/LUCK_FINANCIAL_FACT_REPAIR_2026-10-03.json
```

Then, only as part of separately authorized deployment/repair activation:

```sh
.venv/bin/python scripts/apply_financial_fact_repair.py ../../docs/audits/LUCK_FINANCIAL_FACT_REPAIR_2026-10-03.json --apply
```

On Oracle, run the same script inside the deployed API container using its configured database; no credential belongs in the command or manifest. Schema migration command: none for this patch. Do not run the ordinary extraction/index workers to apply this repair.

## Limits

Only the three implicated reports were reprocessed. The other four LUCK reports and other companies were not audited/repaired. This does not claim all existing financial facts are valid. Ambiguous split-row EPS and mixed-duration columns remain unavailable to this extractor; source documents remain accessible. Previously saved AI answers are not regenerated. No stale-data, IPS, allocation-verification or event-retrieval work is included.

## Deferred all-company follow-up

The user explicitly deferred the all-company audit/repair. The read-only Oracle inventory found 116 companies, 1,247 reports with extracted facts and 14,336 fact rows. Only the existing three-report LUCK manifest is authorized for activation now. Shared parser/reader safeguards apply globally; other historical company records will not be reprocessed in this deployment.
