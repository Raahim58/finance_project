# Oracle verification: daily market data, shares and corporate actions

Implemented and deployed October 4, 2026. Scope is the first three saved market priorities; Tavily/UI/model changes are excluded. Implementation committed as `f622fe6`; no remote push was requested.

## Verified deployment

- API healthy; dedicated `market-scheduler` running with `unless-stopped` and PostgreSQL single-instance coordination.
- Validation batch `psx-market-daily-verify-20261004` exited 0. Prices, indices, capitalization and payout pages have independent durable completed stages. Recurring startup reused completed stages rather than refetching/reinserting them.
- Existing app at `http://127.0.0.1:13000/` returned HTTP 200; its tunnel remains running.
- Persistent PostgreSQL data bind verified as `/srv/psx/postgres`; data disk retained 113 GiB free, root 25 GiB free. Compose recreated dependency containers during initial validation without changing their data bind. PostgreSQL shared-memory ceiling remains the existing 64 MiB; it was not tuned in this scope.
- 57 offline regression checks passed locally. An attempted production-container pytest invocation could not run because the production image does not include pytest; do not claim that suite passed inside Oracle. Actual ingestion, idempotent reuse, source evidence and analytical continuity were checked against Oracle directly.

## Prices and indices

| Session | Accepted company prices |
|---|---:|
| 2026-10-02 | 467 |
| 2026-10-01 | 464 |
| 2026-09-30 | 467 |
| 2026-09-29 | 475 |
| 2026-09-28 | 464 |

These counts are accepted observations, not certified coverage of all active securities. DPS's symbol directory includes historical/special symbols; missing directory symbols remain diagnostic entries and are not proof of current trading or delisting. Invalid OHLC rows remain quarantined.

KSE100 and KSE100PR current-month stages each returned two closes, with zero new insertions because verified observations already existed. Their different return bases remain explicit.

Six confirmed history failures were repaired and retried successfully:

| Symbol | Month | Valid source rows |
|---|---|---:|
| FRCL | 2026-08 | 16 |
| PAKL | 2026-08 | 16 |
| ANSM | 2026-09 | 22 |
| BAFL | 2026-09 | 22 |
| COLG | 2026-09 | 22 |
| KHTC | 2026-09 | 20 |

Nine stale queued records were attempted once against the actual source: WHALE/WYETH August; AEL/AKZO/BYCO/CPAL/CYAN/DAWH/DKL September. All returned no validated OHLCV and now have explicit failed coverage states. Final month ledger: August 468 complete / 23 failed; September 467 complete / 7 failed; no queued/running records in those periods. Empty responses and alias/eligibility reconciliation remain unresolved. Earlier multi-year gaps are not claimed complete.

## Capitalization

Official workbook: https://dps.psx.com.pk/download/indhist/2026-10-02.xls

- 557 source rows in the all-shares sheet; 555 validated.
- 550 matched instrument observations stored, selected and idempotent.
- Rejected INMF/PACE because share/price/capitalization fields failed validation.
- Unmatched: ANLPS, GEMBCEM, GEMNETS, GEMPACRA, SLCPA. No identities were invented.
- Source artifact `de4dc2ef-46a6-4b29-a03d-381a20006416` retained with digest.
- Stored ordinary shares/free float/published market cap/volume/ISIN/index percentage weights. Total shares come from the all-shares sheet, never index-sheet free-float counts.
- October 2 canonical market read returned 469 rows including two index observations; 466 had matching-date capitalization. Whole read took 1.347 seconds in this sample. Capitalization adds one batch lookup rather than one additional query per company.

Sample source-backed latest records:

| Symbol | Close PKR | Ordinary shares | Published market cap PKR |
|---|---:|---:|---:|
| SYS | 115.84 | 1,473,404,435 | 170,679,169,750.4 |
| MARI | 635.22 | 1,200,622,500 | 762,659,424,450 |
| LUCK | 410.56 | 1,465,000,000 | 601,470,400,000 |

## Corporate actions

Official payout archive https://dps.psx.com.pk/payouts supplied 715 source rows across eight bounded pages. After verified notation corrections and reparsing retained pages, 690 matched component announcements are stored: 649 cash-dividend, 18 bonus, 23 rights announcements. Multiple components can occur in one source row; source-row and component counts are different. Six parsed components had unmatched identities. Remaining unsupported/NIL/malformed formats remain diagnosed, not inferred.

Percentages, announcement dates and book closures are stored. Cash per share, ex dates and settlement dates are not inferred from percentages/book closures. Announcement types are not eligible for analytical adjustment or ledger application.

Additional reviewed actions:

- SYS 5-for-1 split, effective 2025-05-31; action `ef8ebc21-917c-4a3b-acf9-5f383f536852`. Official issuer notice: https://dps.psx.com.pk/download/document/254645.pdf. Pinned PDF digest/page excerpts checked by importer. Verified first post-action previous close on June 2: 108.82 versus close 103.40. Handles effective dates without a trading observation.
- MARI 800% bonus, gross share multiplier 9, ex-date 2024-09-16; action `aa3756b7-7cbf-4b23-aff4-3a5f072eff7e`. Explicit ex-date/bonus from official calendar page 27: https://dps.psx.com.pk/download/quote/2024-09-13.pdf. Available before/after adjusted closes 392.9811111111 / 415.90, a 5.832% price change rather than the mechanical 9-fold drop. Gross analytical adjustment does not credit holdings or model individual withholding tax.
- Existing LUCK split remains effective: available adjusted closes 350.29 / 358.88, +2.452%.

Raw prices and holdings were not rewritten. This is a split/bonus-adjusted price view, not dividend-inclusive total returns. Full all-company action history, verified dividend cash/payment inputs and more complex rights/tax handling remain unfinished.

## Commands and remaining limits

Setup, existing-schema migration, scheduler commands and offline checks: [daily market operation](../DAILY_MARKET_AND_CORPORATE_ACTIONS.md).

Daily operation starts after 18:15 Karachi and checks five recent weekdays. It is EOD, not intraday. Successful stages are reused; failures retry no more frequently than every two hours. One source's failure cannot undo another committed stage. No model calls, portfolio ledger application, broader research scheduler activation or new embedding/reindex pipeline occurs in this job.

Remaining: source-empty historical records and alias/eligibility reconciliation; earlier history gaps; two invalid capitalization rows and five unmatched identities; unsupported payout forms; complete reviewed action/dividend history; existing storage/backup/shared-memory/deployment pause-resume controls. Tavily is next after these first-three implementations, not part of this change.
