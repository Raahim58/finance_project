# Company UI and data mechanisms

Reference: `work/ui-proposal/images/company-overview.png` and `company-fundamentals.png`. The implementation is on `ui-updates`, with Overview, Fundamentals, Events, Reports and Portfolio fit. Ask opens over the right context column and retains saved chats.

| Display | Stored source and mechanism | Missing/limited state |
| --- | --- | --- |
| Company identity/logo | Company directory plus database-served, sourced website icon | Symbol fallback; no guessed logo |
| Price and charts | Canonical SQL quotes and selected daily history; quote refreshes hourly and on return to the page | Dated observations; no fabricated intraday path |
| Market cap and share counts | Latest official capitalization workbook on or before quote date | Snapshot date and source stay visible; no silent repricing with the live quote |
| Statement values | Canonical `company_facts` structured section; preserves value, unit, duration, period, basis, ID and source label | Extracted evidence remains marked for source review; no RAG-derived numerical value |
| Ratios | Only explicit backend `derived_fundamentals.ratios` results | Required-input inspector, formula and missing eligibility; no browser calculation or screening-metric substitution |
| Reports | Company-scoped document API plus retained/indexed report coverage | Real URLs, publication dates and indexing status; no invented filings |
| Company brief | Saved digest and prepared evidence with references, current/previous state and provider/job status | Prepared evidence is separate from AI interpretation; previous interpretation remains visibly dated |
| Portfolio relevance | Owned portfolio selected explicitly; stored holdings and canonical valuation | Empty selection has no portfolio context; incomplete valuation hides weight |
| Portfolio evaluation | Existing deterministic evaluation/proposal API, mounted under Portfolio fit | Explicit evaluation; saving a proposal never changes holdings |

Page resources load independently. The `display_only=true` Company request reads Company facts and, when selected, Portfolio and IPS sections. It does not build risk, sector, macro, event or RAG analysis merely to paint the page. Existing analysis calls still request their full canonical context. Ownership checks remain in the canonical builder and backend portfolio services. Assistant company scope is validated against the user's returned owned portfolios; it is never inferred from question text.

All returned statement rows matching the period and accounting-basis controls render, replacing the earlier eight-row cutoff. The canonical Company section currently has its own bounded fact window; this UI does not claim to expose unlimited historical records. Recent reports show three rows; Reports shows the full returned company document/report collection. The document API itself is bounded. Conflicting accounting bases are displayed separately rather than silently averaged.

Ratio completeness requires an eligible numerator/denominator (or trailing EPS/dividend series), compatible reporting period/duration, currency and monetary scale, accounting basis, original source references, and a valid nonzero denominator. A missing input cannot be treated as zero. Current/quick/cash ratios additionally need current liabilities and their respective current-asset components. ROE needs average equity. P/E and yield need trailing per-share inputs; annual values are not silently called TTM. The existing secondary-financial eligibility gate remains closed until fiscal periods, basis, duration and units are reviewed. This work adds display/inspection mechanisms, not fabricated input coverage or an override of that gate.

Formulas are labelled explicitly. The cash-ratio convention here is cash and cash equivalents divided by current liabilities; a short-term-securities-inclusive convention is distinct. Quick-ratio components follow the [CFA Institute ratio list](https://www.cfainstitute.org/sites/default/files/-/media/documents/support/programs/cfa/cfa_program_level_ii_financial_ratio_list.pdf).

Setup/validation:

```sh
cd apps/web
npm ci
npm run typecheck
npm test -- lib/company.test.ts components/CompanyDigest.test.tsx components/AssistantWorkspace.test.tsx
```

No new schema or seed data is required. Existing migration command, when deploying a database behind the repository head:

```sh
docker compose -f compose.oracle.yml exec -T api alembic upgrade head
```

This does not change the hourly market-ingestion schedule or worker topology. Remaining coverage must be repaired in source ingestion/reconciliation and deterministic backend calculations; placeholders cannot solve it in CSS. Company risk and portfolio briefs remain in the later agreed implementation phases.
