# Verified PSX sources and concrete pipeline scope — 6 October 2026

This continues the [backend investigation](2026-10-06-assistant-backend-investigation.md). It translates the supplied US-system description into changes for our existing backend. Source checks were bounded, public, read-only requests; there were no database imports, model calls, migrations, deployment changes or worker starts. [Request evidence](2026-10-06-psx-source-verification.json) records HTTP statuses, response hashes, parser results and limitations. Checks ran approximately 20:12–20:20 Pakistan time.

## Which sources can work

| Source | Verified result | Recommended role / limit |
| --- | --- | --- |
| DPS/PSX | Public bootstrap, symbol directory, LUCK/FFC company pages, monthly LUCK/KSE100 prices, LUCK EOD series and payout table returned usable responses. LUCK report catalog parsed 53 entries. | Primary market/reference and issuer-disclosure source. Company-page standardized figures are secondary screening data. Statements and detailed figures require original filings and period/basis validation. |
| SCSTrade | LUCK September history returned 22 valid OHLCV rows; all five fields matched DPS on all 22 shared dates. Public snapshot exposes company metrics. Annual grid requests returned 13 income-statement, 29 balance-sheet and 7 cash-flow rows for LUCK, and 13 income rows for FFC in its own session. | Useful secondary numerical source and cross-check. Full-grid request fields and issuer-specific sessions are required. Units, fiscal periods, reporting basis and restatements still need source/filing reconciliation before canonical promotion. |
| Mettis Global News | Latest listing yielded ten articles. Two relevant historical LUCK articles returned full text and metadata. FESCO article extraction preserved the qualification that there is no binding acquisition commitment. | High-priority company, sector and Pakistan macro reporting. Its latest ten-item listing is not a historical archive. Keep reports, analysis, opinion and forecasts typed separately. |
| Mettis Global API product | Official MG APIs page describes company fundamentals, news, corporate calendars and market data via JSON/SOAP/XML. | A genuine vendor-feed candidate, beyond the public news website. No credentials, API sample, price, full coverage, history/revision semantics or reliability guarantee were verified. Evaluate a sample contract; do not claim it already supplies all needed data. |
| NCCPL | Ordinary market-information and UIN requests returned HTTP 403 with no usable records. Official indexed material describes daily FIPI/LIPI. | Intended authoritative investor-flow source, currently manual/authorized-feed scope. Public automation is not verified. FIPI/LIPI flows must not be treated as company shareholder ownership. |

Public source pages: [DPS LUCK](https://dps.psx.com.pk/company/LUCK), [PSX indices](https://dps.psx.com.pk/indices), [SCSTrade snapshot](https://www.scstrade.com/stockscreening/SS_CompanySnapShot.aspx?symbol=LUCK), [SCSTrade financial page](https://www.scstrade.com/stockscreening/SS_CompanySnapShotYFNew.aspx?symbol=LUCK), [Mettis FESCO article](https://mettisglobal.news/Lucky-Cementled-consortium-submits-EOI-cleared-for-FESCO-due-diligence-63034), [MG APIs](https://mettisglobal.news/MGAPIs), [NCCPL UIN](https://www.nccpl.com.pk/uin).

### Match the data to the source

| Data needed | Main route | What is still missing or conditional |
| --- | --- | --- |
| Current/daily equity prices and volumes | DPS, SCSTrade cross-check | All-company parity and uninterrupted scheduling; preserve trading date and source adjustment basis. |
| Historical OHLCV | DPS monthly tables; SCSTrade fallback | One month/issuer checked, not complete history. EOD chart series must not be assumed to contain full OHLCV or raw split basis. |
| Benchmarks/sector market context | PSX indices and official market observations | Retain KSE100 versus KSE100PR definitions; no fabricated index averages. |
| Symbols, names, classification, fiscal year-end | DPS reference/company pages | Directory contains mixed instruments; 1,032 rows are not 1,032 ordinary active stocks. Resolve instrument eligibility and issuer aliases. |
| Shares, free float, capitalization | DPS equity profile/downloads; SCSTrade comparison | Effective dates and full-universe contract not certified by snapshot presence. Derive capitalization only from compatible dated inputs. |
| Sales, earnings, EPS and margins | Original issuer statements; DPS screening and SCSTrade secondary data | DPS annual/quarter labels currently misdated by our parser for non-calendar issuers. |
| Debt, cash, assets, equity, operating/investing/financing cash flow | Original filings; verified SCSTrade annual JSON candidate | JSON accessibility confirmed; units/basis/restatement and cross-company reconciliation still required. |
| Dividends, splits, bonuses and rights | PSX announcements/payouts and original issuer notices | Percentage of par is not yield. Announcement/book closure is not automatically payment or ex-date. No complete action history certified. |
| Insider disclosures | PSX originals; SCSTrade convenient indexing | Preserve named person, transaction date, action and original filing; do not infer motive. |
| Company ownership / institutional holdings | Issuer ownership schedules and source-reviewed holdings disclosures | SCSTrade Funds Holdings page existence does not verify an accessible, complete historical holdings feed. |
| Foreign/local investor flows | NCCPL | Automatic public access blocked; existing importer needs a normalized CSV, not an assumption that every raw NCCPL export fits it. |
| Company news / expansion / financing / acquisition plans | Mettis, PSX announcements, issuer IR | Mettis historical examples accessible; complete company/event discovery is not proved. |
| Sector drivers / macro / geopolitical text | Mettis and existing curated official/global sources | Need company exposure/context matching. These four alone do not establish comprehensive global coverage. |
| Exact macro, FX, interest rates and commodity histories | Separate official numerical adapters or verified licensed feed | Public news/sidebar numbers are not a complete time-series feed. MG API is a candidate, not certified coverage. |
| Analyst forecasts, target prices and ratings | Dated SCS/Mettis research; original rating agency releases for credit ratings | Broker estimates are not reported actuals or consensus. No complete analyst-consensus/ratings history verified. |
| Earnings-call transcripts / presentations | Official briefings and issuer IR; authorized provider if available | No complete public transcript feed among these four verified. |

DPS terms restrict systematic automated reuse without permission; technical accessibility is not a production feed licence. MG explicitly offers application/redistribution integration, subject to its actual contract. This is a source-selection constraint, not a request to activate anything. [DPS terms](https://dps.psx.com.pk/company/LUCK), [MG API product](https://mettisglobal.news/MGAPIs).

## Concrete failures discovered during verification

**DPS financial dates:** `dps_standardized.py:_period` converts every annual label to December 31 and Q1/Q2/Q3/Q4 to calendar-quarter ends. The live LUCK page explicitly says fiscal year-end June. Our parser mapped FY2026 to December 2026 and Q3 FY2026 to September 2026, instead of resolving the issuer's fiscal calendar and original reporting bounds. FFC's December year-end happens to fit the rule. Correct calendar resolution and affected stored rows before using these values in growth, valuation or brief generation; do not change the original values merely because dates are wrong. [Parser](../../apps/api/app/providers/fundamentals/dps_standardized.py#L47).

**SCSTrade financial session:** financial HTML contains empty grids whose scripts load public JSON. Minimal `{"sym":"LUCK"}` requests returned 500; the page's full grid fields worked. More seriously, passing FFC in the existing LUCK page session still returned LUCK data. Opening a fresh FFC page session returned a different FFC dataset. Issuer verification and isolated sessions are mandatory; HTTP 200 does not establish the right company. Empty HTML is not proof there is no financial data.

**Mettis timestamp:** FESCO metadata says `2026-08-28T16:09:33Z`, while visible text labels 16:09 as GMT+05:00. These differ by five hours as instants. Preserve both raw timestamps and record the conflict. Establish a source-specific normalization rule before using minute-level freshness or market-reaction matching. Do not silently subtract five hours from every article without validating the source contract.

**Mettis coverage:** the earlier read-only Oracle snapshot had Mettis disabled with no successful poll despite a working existing parser. Source accessibility and scheduled coverage are different. Expand the approved source selection and monitor company coverage in a separately authorized change; restarting the same ten-source set alone will not add Mettis. PSX announcement live selection was also disabled in that snapshot; historical announcement documents do not prove current disclosure coverage.

## The pipeline to build incrementally

```text
Approved source lanes
    ↓
Save discovery metadata + source identity + observed dates
    ↓
Known URL/story duplicate? → attach to existing story
    ↓
Worth fetching? → bounded fetch, save unchanged original
    ↓
Body duplicate / invalid date / weak extraction / wrong issuer?
    → retain diagnostic or quarantine; do not certify
    ↓
Company, sector or macro relevance + material new information?
    → select for indexing; otherwise raw only
    ↓
Parse by document type; save facts/events/passages with references
    ↓
Refresh affected company-intelligence sections
    ↓
Question-specific evidence + selected portfolio/IPS/calculations
    ↓
Answer with original citations and explicit gaps
```

**1. Fix source and fact contracts first.** Keep separate lanes for numerical observations, filings, announcements, articles and research. Use DPS primary, SCS secondary, Mettis company news and optional verified MG API. NCCPL stays manual/authorized until a usable contract exists. Correct fiscal periods and isolate SCS company sessions. Exact values use database facts; vector search serves document text.

**2. Make raw capture replayable without unbounded downloading.** Keep discovery metadata for approved sources even if not promoted. Store original fetched bodies/PDFs with hashes and a retention budget. Fetch approved official disclosures broadly across the eligible universe; prioritize deep enrichment of holdings/watchlists/researched companies without making alternatives invisible. The supplied 100K-document example is illustrative, not our server budget. Body hashing needs a body fetch; URL/story-ID checks can happen before it.

**3. Replace coarse promotion with recorded decisions.** Record why an item was accepted, rejected, deferred or raw-only. Direct company match uses explicit tickers or verified aliases; ambiguous words require context. Broader articles need an identifiable channel—company business/geography, costs, demand, regulation or funding. A generic occurrence of “investment,” “profit” or “cement” is insufficient. Rank original material information and contrary evidence above generic corporate copy. Reserve coverage for company developments, sector drivers and macro/geopolitics; allow empty results.

**4. Deduplicate stories and passages across the whole pipeline.** Canonicalize URLs/provider IDs, then use body hashes and near-duplicate comparisons. Keep different sources and materially different claims as separate support; ten copies of one release are not ten independent confirmations. At chat assembly, deduplicate the saved-intelligence passages against fresh search. Retain distinct evidence spans but send document metadata once.

**5. Process once and build reusable intelligence.** Parse articles by paragraphs, filings by sections/tables/footnotes, and presentations by pages/slides. Index accepted text once. Preserve exact fact values, units, currency, reporting basis, period start/end, source date/version and quote/page. Save events with fact/management-claim/interpretation distinctions. Start with transparent rules; add a reranker or classifier only when labelled examples show what it improves. Do not add paid extraction to every article.

Company intelligence has dated sections for performance, drivers, expansion, dividends, developments, sector/macro effects, risks and unanswered questions. Each statement identifies evidence and a verification state. New material evidence refreshes affected sections; daily market overlays remain separate. A saved model interpretation cannot become authoritative just by being saved.

**6. Make chat consume the useful result.** Automatically supply relevant intelligence sections, fresh material events, the selected owned portfolio, confirmed IPS/goals/required return, and required deterministic calculations. Fetch missing detail automatically. Avoid the full snapshot plus brief plus repeated search and source trees. Preserve original citation references through follow-ups. Source-linked facts survive compression; unrelated evidence does not get kept merely to fill slots.

**7. Treat stock movement as a prioritization hint.** A stock moving while an article arrives can increase investigation priority. It does not establish causation. Account for sector moves and recorded corporate actions before connecting an event to price movement. This hint must not exclude quiet but important disclosures or introduce future information into historical tests.

**8. Fix scheduling recovery and evaluate outcomes.** Restore intended producers after successful deployments, monitor source lag, track archive windows independently from live work, and keep retries/cursors durable. Validate labelled direct/indirect event relevance, numerical exactness, qualifications, cross-issuer isolation, citation resolution, duplicate suppression, total provider input and end-to-end latency together. Test the same questions before/after; a smaller JSON is not a quality pass.

The supplied answer settles the overall separation of ingestion and runtime work. It does not justify five physical stores, a knowledge graph, a complete ML-classifier stack or ingesting every approved body indefinitely. Our existing database, search and queues can support the first increments. No implementation or activation was performed here.
