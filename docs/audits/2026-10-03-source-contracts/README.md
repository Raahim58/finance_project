# News source contract verification — Oracle, 2026-10-03

This executes step 1 of the [post–Phase 11 plan](../../POST_PHASE_11_INGESTION_AUDIT_AND_EXECUTION_PLAN.md). Verification used the deployed adapters from Oracle, not the local Mac network. Thirty-seven sources were checked, normally with at most two article fetches per source. Focused checks fetched two additional dated OFAC actions and two geopolitical Al Jazeera news articles; production PDF/date checks revisited selected official/Mettis samples. No ingestion, model calls, database writes or queue writes were performed.

The first pass discovered candidates for 30 sources and fetched 60 samples. Six sources returned HTTP errors; one returned zero candidates. Discovery and raw/body hashes, request methods, URLs, content types, parser results, dates and short body excerpts are retained in the JSONL files. These are diagnostic manifests, not complete raw-response fixtures or proof of sustained coverage. Current source access must be rechecked at activation.

## Verdict

There are enough accessible sources to improve current coverage substantially. Do not enable the entire source catalog unchanged: some adapters return previews or navigation, publication metadata is incomplete, and the reporting-source relevance gate rejects sampled geopolitical evidence before reading it. HTTP 200 and `parsed > 0` are insufficient acceptance criteria.

“Contract passes” below means that discovery plus readable dated text passed the small sample; it does not mean the production selection/indexing funnel or a seven-day reliability canary has passed.

## Pakistan sources

| Source | Observed contract | Decision |
| --- | --- | --- |
| Dawn | RSS → HTML; 2/2 readable dated articles, 1,254/380 words | Contract passes; retain 300s cadence |
| Business Recorder | RSS → HTML; 2/2 readable dated articles, 701/297 words | Contract passes; retain 300s cadence |
| Mettis | Listing → HTML; 1,234-word article and 46-word indicators/link page; JSON-LD date conflicts with displayed GMT+05 time | Conditional: correct timezone conflict handling and reject/label link-only pages before relying on freshness |
| SBP releases | Media-center listing selects old 2025/2023 rebuttals first; no publication metadata. PDF text works via production parser | Repair current-release discovery, dates and navigation exclusion; do not count this as a current policy-release contract |
| Finance Ministry | First two candidates are budget navigation pages; both normalize to the same 256-word generic updates text; dates missing | Repair discovery row/attachment association and article extraction; wrong title/body association blocks use |
| PBS releases | August and September 2026 CPI PDFs accessible; production parser extracts 1,513/1,528 words across 3 pages each; publication dates missing | Useful verified recovery documents; add release/period metadata before scheduled current coverage. Exact CPI values require structured parsing/validation |
| SECP | Discovery returns HTTP 403 | Keep dormant until a working ordinary contract is verified |
| NEPRA | September attachment PDFs reachable; production parser gets readable text; headline/row dates absent | Conditional: associate report title/date with attachment; distinguish notices, decisions and press releases |
| OGRA | Listing includes itself as “Media Centre” and an attachment labeled “EN”; PDF contains a readable dated August 31 release, but candidate date missing | Repair self-link rejection, title/date association and release ordering |

Mettis date evidence: the first sampled page displays 02:15 PM GMT+05:00, while JSON-LD says `2026-10-03T14:15:23Z`. The audit at approximately 12:43 UTC therefore receives a future timestamp. Preserve both observed representations and flag the conflict; do not silently trust the `Z` label or globally reinterpret all publisher dates.

## Geopolitics and global markets

| Source | Observed contract | Decision |
| --- | --- | --- |
| BBC World | RSS → dated HTML; 745/551 words | Contract passes; 900s cadence |
| Guardian World | RSS → dated HTML; 738/618 words | Contract passes; 900s cadence; RSS is not an August archive |
| Al Jazeera | Feed and HTML now accessible. First feed samples include a 48-word video description and sport. Focused `/news/` samples yield 333/549 words | Conditional: capture fixtures for recovered access, filter non-article items, verify relevance admission; old DNS-disable reason is stale |
| Zeteo | Feed → dated public HTML; 714/282 words | Public-text contract passes; retain commentary/reporting distinction |
| Associated Press | World listing returns HTTP 403 | Keep dormant; earlier successful canary is stale |
| OFAC | Current dated action URLs reachable; readable 304/1,775-word text. Generic discovery also selects the “Sanctions List Updates” index; parsed publication date absent | Repair index exclusion, observed action dates and relevance admission |
| GDELT | Discovery returns HTTP 429 | Remain supplementary/dormant; not the August-recovery dependency |
| IMF news | Listing returns HTTP 403 | Keep dormant |
| CNBC | RSS → dated HTML; 948/1,526 words | Contract passes; 900s cadence |
| Nikkei Asia | Feed accessible; article samples only 94/84 words | Limited-preview evidence, not verified full text; require explicit depth labeling |
| Federal Reserve | RSS → dated short releases; 121/193 words | Contract passes for sampled releases; short official statements need not be rejected solely for length |
| ECB | RSS → dated text; 2,089/2,994 words | Contract passes |
| BIS | RSS → dated text; 921/389 words | Contract passes |
| World Bank news | HTML fetch succeeds but produces zero matching candidates | Discovery contract fails; zero must not be treated as a healthy broad-news source without inspection |

### Production relevance checks

The focused run uses the existing scoring functions against a read-only PostgreSQL transaction; it does not run discovery/fetch/parse persistence stages.

- Two Al Jazeera geopolitical news samples score `0.0` at metadata stage and fail the `0.18` fetch threshold. One reaches `0.56` when full text is evaluated, which exceeds the `0.30` parse threshold. Enabling the feed would still discard that sample before reading it.
- OFAC's October 1 Iran-related action scores `0.14` on metadata and fails fetch admission, but scores `0.74` on the full text. Its October 2 counter-terrorism action scores `0.0` on metadata. Both would be discarded before extraction by the generic gate.
- OFAC is in the official canary group, whose fetch path exempts it from the cheap metadata cutoff; its full-text gate and missing dates still need checking. The metadata failure is consequential for reporting breadth sources such as Al Jazeera, not proof that the official OFAC fetch path rejects the action.
- The scorer also reports `coal` for the Ethiopia article. The implementation uses substring matching, so a matched term alone does not establish coal-market exposure; these manifests do not prove which occurrence triggered the match. Add token/phrase boundaries and review geopolitical relevance examples before trusting these reasons as evidence of market transmission.

Fix with curated positive and negative examples: relevant regional conflict/sanctions/shipping stories should be eligible for bounded reading, while sport, video descriptions and general political coverage without an applicable channel must not flood the index. Do not lower all thresholds or make publisher tier alone sufficient for company exposure.

## Energy, shipping and sector sources

| Source | Observed contract | Decision |
| --- | --- | --- |
| gCaptain | RSS → dated text; 500/537 words | Contract passes; 1800s cadence |
| FreightWaves | RSS → dated text; 1,235/752 words | Contract passes; 1800s cadence |
| LNG Prime | Both articles contain 34–37 words and an explicit annual-subscription notice | Preview-only. Do not index as complete reports or claim dependable full-text LNG coverage |
| EIA releases | RSS → readable official releases, 352/372 words; latest sampled release September 9 | Contract passes for release evidence; release frequency differs from market-price frequency |
| OPEC | Listing returns HTTP 403 | Keep dormant; use other verified energy evidence while repairing ordinary access |
| Cotton Grower | RSS → dated text; 1,154/341 words | Contract passes; 3600s cadence |
| Fertilizer Daily | Feed returns HTTP 403 | Keep dormant; fertilizer reporting remains a coverage gap needing a verified replacement |
| Coal Age | RSS → dated text; 263/497 words | Contract passes; 3600s cadence |
| Malaysian Palm Oil Council | 52-word speaker/profile page and 173-word dated market report | Conditional: exclude program/profile pages; accept relevant reports with depth labels |
| MetalMiner | RSS → dated text; 1,290/1,267 words | Contract passes; 3600s cadence |
| Steel Market Update | Dated 377/153-word samples; first is a newsletter-format notice | Accessible contract; filter publisher housekeeping, preserve article-depth limitations |
| Semiconductor Engineering | RSS → dated text; 230/266 words | Contract passes for sampled text; inspect relevance/fragment depth during canary |
| EE Times | RSS → dated text; 1,045/1,502 words | Contract passes |
| Electrive | RSS → dated text; 334/404 words | Contract passes |

## Production PDF verification corrects the smoke result

The existing `evidence_source_smoke` and initial audit pass call `source.normalize(raw)` on every content type. For generic official sources this runs HTML extraction on PDF bytes and reports high quality for PDF syntax/gibberish. **That is a smoke-tool defect, not evidence that the production PDF worker uses HTML.** Production dispatch sends PDFs to `parse_stage(..., pdf=True)` and `_pdf_evidence`.

The second pass uses `_pdf_evidence` directly without database writes. SBP, PBS, NEPRA and the OGRA attachment produce readable text there. Publication dates remain absent because the generic listing does not supply them and this PDF helper retains the candidate date. No official source receives a full current-release pass just from a readable PDF.

Required verification-tool improvement before future activation checks: route content types through the production parser, report missing publication dates, detect title-only fallback and preview/navigation content, and distinguish parser success from acceptance. Use small offline fixtures; never use PDF-byte word count as quality evidence.

## August recovery contract status

- PBS's observed listing directly exposes August and September CPI releases, and both PDFs passed the production text parser. OGRA's sampled attachment has an August 31 date inside the text. These prove specific recoverable documents, not exhaustive month coverage or validated numerical series.
- SBP/Finance Ministry/NEPRA/OGRA need dated row/attachment association and archive traversal contracts before an August catch-up can be declared complete.
- Current RSS article checks do not prove that August–September geopolitical reporting can be recovered. The existing historical preset supports GDELT only for general news, and GDELT remains throttled.
- Implement at least one tested dated geopolitical archive/API route and one Pakistan reporting archive route. Guardian Content API remains a candidate requiring a configured authorized key and verified pagination/date filters. No such new adapter was tested or represented as implemented by this run.

## Concrete changes before activation

1. Correct smoke verification to use production HTML/PDF paths and trustworthy quality/date states.
2. Capture minimized offline fixtures from observed contracts, including recovered Al Jazeera, blocked responses, mixed article/video items, PDF routing, missing dates, duplicated navigation text, subscription previews and Mettis timezone conflict. These manifests retain hashes/excerpts; they do not substitute for parser regression fixtures.
3. Repair official row/attachment discovery and publication metadata; avoid navigation/self-links and check that title and body refer to the same document.
4. Fix geopolitical relevance admission and substring false positives with curated fixtures. Preserve the existing official-group exemption when assessing fetch behavior.
5. Add explicit preview/short-release/navigation classifications; do not treat all short bodies identically.
6. Build the missing dated archive contracts for August recovery. Current evidence polling can proceed once its own gates pass; it need not wait for every archive.
7. Use an explicit activation source selection. Keep AP, IMF, OPEC, SECP, Fertilizer Daily and GDELT disabled pending fixes; World Bank discovery is not ready. Current breadth flags alone would enable some failed sources.

Priority current-source candidates are Dawn/Business Recorder, BBC/Guardian, gCaptain/FreightWaves, the passing official global releases and relevant sector feeds. Al Jazeera and Mettis are useful additions after their demonstrated gate/date issues are resolved. Full-text LNG and fertilizer breadth still need replacements or verified authorized access.

## Company prices and other missing data — added investigation

Read-only Oracle queries and four bounded DPS company-page checks were performed on October 3, approximately 19:39–19:40 Asia/Karachi. These checks distinguish a company with no stored observations from stale observations and from fields the adapter never supplies. The per-company manifest contains all 862 stored symbols, including active state, price counts/latest date and financial-fact counts; it is the drill-down for specific missing companies.

### Why exactly 247 active records have no prices

Follow-up verification read the **retained original DPS symbol directory and August 13 daily-price response**, rather than attributing every missing symbol to today's broken endpoint. The directory contains all 247 symbols, so these company records exist. Their prices were never successfully stored.

| Original daily-price response | Missing companies | Established reason |
| --- | ---: | --- |
| Symbol absent from the source table | **244** | The symbol directory created an active company record, but that date's price response supplied no row for it |
| Symbol present, OHLC validation rejected it | **3** | AGLNCPS, JVDCPS and NATM each had a reported close below its reported low; the adapter quarantined inconsistent rows |
| Symbol present and accepted, yet absent from DB | **0** | This sample does not show accepted daily rows silently disappearing for these 247 |

These counts sum to 247. The three rejected rows report: AGLNCPS low 48.33 / close 43.94; JVDCPS low 56.65 / close 56.13; NATM low 94.15 / close 89.42. These are **raw source values quoted to explain rejection**, not validated prices to display or use in analysis. Correcting them requires another verified observation/source, not disabling validation.

**Why did historical ingestion not fill them?** Of the same 247 companies, **239 have no price-history work ledger at all**. The scheduler queues history only for its selected deep set. The remaining **eight—AKZO, CPAL, ICCT, ISTM, JPGL, PGCL, SGABL and SING—have 488 failed monthly history units**, all reporting no validated OHLCV; AKZO and CPAL also each have one queued unit. These are an independent breakdown of the same companies, not an additional 247 gaps.

The active-company count is therefore a directory/eligibility count, not proof of current trading or price availability. The retained directory supplies only symbol, name, sector and debt/ETF/GEM flags, with no explicit active/trading-status field. Thirteen of the missing company names explicitly contain “Right”; the existing directory filter removes debt/ETF/GEM but does not separately exclude rights or establish their trading status. The directory includes symbols with no rows on the selected day. The retained daily response alone does **not** establish why each of the 244 was absent—no trading, listing changes, aliases, source omissions and parser/retrieval problems in historical requests still require individual evidence. Do not label all 244 delisted or all 247 ingestion failures.

Today's stopped schedulers and `/symbols` 404 explain why the situation remains unrecovered and stale; they do **not** explain why those 247 were initially missing in August.

Evidence: original directory artifact `7fce0e03-3c5c-44cc-b353-91e86d20a860`, SHA-256 `f61f031aeebaa54f50f34575140c0359fb3eedef7e855ab06f769cb225cdb109`; original daily artifact `97815734-0f3f-4f3f-885e-f3d7ef75a59c`, SHA-256 `2e353cb40b9296d93f2c1f13d4f0fec564b705b67bb9f5b92587533e519dfce1`. The daily artifact's effective timestamp is August 13 midnight Karachi (August 12, 19:00 UTC). Both were retained from August 15 ingestion. The [247-company CSV](missing-price-companies.csv) records the source-response reason and history-ledger state for every affected symbol; the [trace manifest](missing-price-trace.jsonl) contains the exact lists, artifacts and rejection cells.

### Verified extent

| Dataset | Stored coverage | Implication |
| --- | --- | --- |
| Active company records | 740; all have an Instrument; 52 have `Unknown` sector | Missing Instrument IDs are not the explanation; classification remains incomplete |
| Prices among active records | 493 have any prices; **247 have none**; 478 have August 13 prices, 15 have older last observations | 33.4% of the stored active universe has no price at all; every stored price is stale for current use |
| Inactive company records | 122; all have August 13 prices; 111 have `Unknown` sector | Stored listing/eligibility state needs reconciliation, not a blanket assumption that all absent prices mean source failure |
| Canonical price observations | 615 instruments; 109,031 selected observations, matching the legacy price-row count | The missing-company problem is not explained by a wholesale failure to select stored prices; per-endpoint/UI behavior still needs separate checks |
| Market capitalization | NULL in all 109,031 `market_prices` rows | DPS daily OHLCV does not populate this field; restarting its scheduler alone will not supply it |
| Standardized fundamentals | 18,320 facts for 625 active instruments; 115 instruments have zero facts and `partial` coverage | Broad financial coverage ran, but empty/parser-unrecognized pages remain unresolved |
| Detailed filing facts and reports | Facts and symbol-linked reports for 116 active companies | Broad standardized coverage is not full-market balance-sheet/dividend/debt coverage |
| Screening | Last computed August 15: 740 instruments, 415 screenable, 116 promoted | Selection and underlying inputs are stale; detailed ingestion was concentrated in this selected set |

Of the 247 active records without prices, **141 still have standardized financial facts** and 106 do not. For example, AAL and ENGRO each have 20 standardized facts but no price rows; ICI and SHEL each have 36 facts but no price rows. This is evidence of distinct price and fundamentals coverage, not proof that those symbols currently trade. AGLNCPS has neither. The 15 active records with older prices are AEL, BYCO, CYAN, DAWH, DKL, FFBL, GVGL, HCL, HSM, KHSM, MCBAH, PMPK, SFL, WHALE and WYETH. Verify sourced listing status and effective-dated aliases before using any of these as current eligible symbols; do not infer a rename/delisting from the ticker alone.

### Causes established by the audit

1. **Current ingestion is stopped, and its price discovery contract now fails.** Running Oracle services are API, web, PostgreSQL, Redis, MinIO and research-worker; no market/Phase 2 ingestion producers or consumers are running. The only market refresh record is August 15, yielding August 13 prices. More critically, a fresh `DpsMarketDataProvider.fetch_latest_prices()` fails with **HTTP 404 at `https://dps.psx.com.pk/symbols`**, before reaching `/historical`. This is independent of scheduler absence: starting the unchanged adapter would fail. No current symbol-universe completeness or current daily-price response was verified by this run.
2. **The universe and price lanes have different inclusion rules.** Current code filters debt, ETF and GEM flags from DPS current-price ingestion, while historical tasks target `deep_instrument_ids`, not every active company. Company creation defaults to `instrument_type="equity"`; configured-reference synchronization and price upserts can set `is_active=True`. A current symbol-list contract was unavailable, so the exact split of the 247 gaps into non-trading, obsolete/alias, special-security and ingestion failure is **not yet established**. The contradictory stored active/inactive coverage is a reconciliation requirement, not grounds to manufacture prices or remove records automatically.
3. **Historical work contains real failures and abandoned reservations.** There are 1,267 failed monthly price-history units: 1,176 `ValueError` failures for no validated OHLCV and 91 `IntegrityError` failures. Recorded constraint conflicts include `uq_sector_stats_sector_date_source` and `uq_market_observation_source`, demonstrating concurrent/idempotency failures, not missing publisher data. Another 100 units remain queued and nine running with last attempts in August/September. Empty validated results need raw-response inspection to separate legitimate no-trade/pre-listing periods from parsing/retrieval failures; repeated generic retries cannot establish coverage.
4. **Empty fundamentals are effectively terminal.** All 115 partial standardized-fundamentals units report “DPS page exposed no recognized standardized financial rows.” `is_queueable()` refreshes completed units after 30 days but has no partial refresh branch; `broad_fundamentals()` also returns immediately for a partial state if directly invoked without re-reservation. The scheduler therefore does not revisit these empty results. Fresh company-page checks produce 32 facts for HBL, 20 for ENGRO, 20 for AAL, and zero for AGLNCPS. Company-page availability persists even though `/symbols` fails, so these failures must be treated separately.
5. **“Other data” extends beyond the broad adapter's scope.** Its seven stored metric families are revenue, total income, net income, EPS, EPS growth, gross margin and net margin. It is not a balance-sheet or full valuation adapter. Detailed financial ingestion is restricted to held/benchmark/promoted/explicitly requested instruments; the 116-company filing coverage is consistent with that architecture. Across stored filing facts, debt covers 59 instruments and dividend-per-share 24, versus revenue 114. There are 142 zero-fact partial extraction units and 14 failed extraction units; failures include 12 missing-artifact `FileNotFoundError`s and two native-text failures. Partial diagnostics also show OCR failures, unknown reporting scales and ambiguous statement rows. These are additional barriers within the deep set, not reasons to invent values.
6. **Coverage can be falsely reported missing through the wrong association.** All 1,391 financial reports have `Document.company_id=NULL` but populated `Document.symbol`, spanning 116 symbols. A company-ID-only report query returns zero, even though symbol-based research/retrieval paths can find reports. Count quarterly reports as well as annual/interim reports. Repair association consistency or use the established symbol/instrument linkage when reporting coverage; this audit does not prove that any particular UI endpoint uses the wrong join.
7. **Some stored period metadata is suspect.** There are 154 standardized facts across 27 instruments and seven filing facts for one instrument with `period_end` after October 3. The standardized parser maps bare years to December 31 and quarter labels to calendar quarter ends; those assumptions can misrepresent issuer fiscal periods. These are date-quality findings, not confirmed future financial results. Validate against the source headers/report periods and quarantine incompatible periods before freshness/comparability or screening decisions.

Code evidence: [DPS current adapter](../../../apps/api/app/services/market_providers.py), [universe/company synchronization](../../../apps/api/app/services/market_ingestion.py), [Phase 2 scheduling](../../../apps/api/app/services/phase2_orchestration.py), [retry policy](../../../apps/api/app/services/coverage_service.py), [task guards and extraction](../../../apps/api/app/jobs/phase2_tasks.py), [deep-set selection](../../../apps/api/app/services/screening_service.py), [standardized parser](../../../apps/api/app/providers/fundamentals/dps_standardized.py), [canonical-price reader](../../../apps/api/app/services/canonical_market_service.py).

### Required execution order for company coverage

1. Repair and fixture-test the ordinary DPS universe discovery contract from Oracle. Then reconcile stored symbols, sourced security types, listing status and effective-dated aliases. Preserve audit history; avoid blanket deactivation or combining old/new symbol histories without verified corporate-action evidence.
2. Establish a per-symbol/per-dataset coverage ledger distinguishing not attempted, stale, unavailable/non-trading, partial extraction, failed and complete. Include available reporting fields and source timestamps; populate consistent report associations. Reconcile the 247 missing-price records against the verified eligible universe.
3. Fix demonstrated concurrent inserts/idempotency in history and sector-stat persistence, missing-artifact retrieval, and bounded refresh/reprocessing for partial fundamentals/extraction. Add targeted tests for duplicate task delivery, expired reservations, empty source results, parser-version changes and period semantics. Inspect capped retry states before selectively requeueing; do not reset every failed unit blindly.
4. Restore Oracle ingestion lifecycle as described in the parent plan. Run a bounded daily-current-price refresh first, verify accepted/rejected counts and dates, then sustain it with the dedicated market scheduler. The old refresh recorded zero attempted/accepted/rejected counters despite writing 478 rows; do not trust that `success` label as a completeness metric. Intraday prices remain a separate contract.
5. Recover missing eligible daily prices and August–September sessions in bounded batches, with current work taking priority. Recompute screening from corrected current inputs. Explicitly decide whether five-year history and detailed filings remain limited to the deep set; if full-market availability is required, expand the documented policy and resource budgets rather than promising that existing Phase 2 queues cover everyone.
6. Implement separately sourced shares/market-cap and additional financial-field contracts where needed. Validate effective dates, units, fiscal periods and corporate actions; any derived market cap/valuation must have the required observed inputs. Preserve unavailable states when they do not exist.

Completion evidence: a reconciled eligible-universe count; per-symbol gap report and reasons; verified current canonical prices; repaired failed/stale reservations; explicit field/deep-set coverage; usable symbol-linked report retrieval; and successful restart/deploy recovery. This investigation changed no company flags, prices, facts, queues or running services.

## Evidence and reproduction

- [Pakistan manifests](pakistan.jsonl)
- [Geopolitics manifests](geopolitics.jsonl)
- [Energy/sector manifests](energy-sectors.jsonl)
- [Global/technology manifests](global-technology.jsonl)
- [Production PDF and date checks](pdf-and-date-checks.jsonl)
- [Focused listing/relevance checks](focused-current-checks.jsonl)
- [First-pass verification script](verify_news_contracts.py)
- [Per-company coverage and bounded live DPS checks](company-coverage.jsonl)
- [Company ledger/extraction/association diagnostics](company-diagnostics.jsonl)
- [Read-only company coverage script](verify_company_coverage.py)
- [Read-only supplementary diagnostics script](verify_company_diagnostics.py)
- [Original-artifact missing-price trace](missing-price-trace.jsonl)
- [247 missing-price companies with reasons](missing-price-companies.csv)
- [Read-only original-artifact trace script](trace_missing_prices.py)

Run the script from the repository root via the deployed API container, passing explicit source keys. It performs at most two sample fetches per source and prints JSONL; redirect output to a local audit file. It intentionally records the original generic normalization behavior; use the production PDF check when interpreting PDF results.

```sh
ssh -i ~/.ssh/oracle_psx ubuntu@141.145.146.120 \
  'cd ~/finance_project && docker compose -f compose.oracle.yml exec -T api python - dawn business_recorder bbc_world guardian_world' \
  < docs/audits/2026-10-03-source-contracts/verify_news_contracts.py \
  > /tmp/news-contract-verification.jsonl
```

This is a source-contract verification result, not an activation or coverage-completion report. No scheduler was started and no source state was mutated.
