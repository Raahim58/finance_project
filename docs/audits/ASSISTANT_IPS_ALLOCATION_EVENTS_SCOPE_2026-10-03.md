# Assistant fixes 2–4: locked scope and implementation

Authorized: reuse existing IPS/compliance services; improve allocation-verification prompt and result handling while the model chooses its tools; make company event tools retrieve existing direct/indirect matches and broader stored news for AI analysis.

Deferred: all-company financial repairs, reindexing, ingestion/backfill, new automatic indirect factors, UI overhaul and provider/model optimization. The implementation run used no model calls, commits or deployment. The user subsequently authorized committing, deploying and checking a live model call; those validation results will be reported separately. No token limits or tool allowances change.

## 2. IPS

Saved Oracle diagnostics identify the historical `ips.compliance` handler failure as PostgreSQL `DiskFull`, at the database cursor. Read-only reproduction of the currently deployed tool succeeds and returns `BREACH` for the existing selected portfolio. A missing handler was not the cause; do not add another IPS evaluator.

`workstation_service.ips_compliance` still uses the existing portfolio ownership check, selected confirmed IPS, stored portfolio summary, quantitative analysis and `evaluate_ips_constraints`.

- Check the selected version belongs to this portfolio and is confirmed before evaluation.
- On the Assistant's `persist_analysis=False` path, isolate optional quantitative reads in a savepoint. A SQL failure then rolls back that operation instead of poisoning the session and losing all available holding/cash checks.
- Catch only HTTP availability failures and SQLAlchemy database errors; no general exception suppression or retry. Return `modeled_analysis` availability, exception type and SQLSTATE, never SQL/parameters.
- Existing evaluator emits actual violations and `NOT_EVALUATED` checks for unavailable modeled inputs. Unavailable calculations are not converted into passing checks.
- Existing workflows that persist analysis retain their commit/error behavior; no transaction redesign.
- No disk cleanup, database setting changes or storage expansion.

## 3. Allocation

`ai/tool_loop.py` prompt now explicitly covers ideal weightage, recommended new weights and rebalancing. Require `allocation.verify` for the exact gross-amount proposal and use its calculated numbers. Current holdings weights and recorded IPS targets do not require proposal verification.

If verification was skipped, failed, rejected or unavailable, instruct the model not to give recommended weights and to explain the gaps/checks. The existing recommendation distinction between arithmetic acceptance and evidence readiness remains.

Final deterministic rendering retains rejected/unavailable states, verification IDs, errors and failed checks, without presenting recommended allocation rows/legs. Accepted calculated rows still render normally. Latest failed verification continues replacing an earlier successful checkpoint result.

No question classifier, mandatory structured proposal field, forced call sequence, automatic verifier invocation, reserved-call scheduler, extra provider call or budget expansion. The existing prompt encourages reserving tool capacity; it is guidance, not backend workflow enforcement. Arbitrary prose is not guaranteed to obey the prompt; do not claim hard enforcement or optimality.

## 4. Events

`research_intelligence_service._company_event_matches` extracts the existing company-page matching logic without changing factor recognition, profile ownership or background digest admission. `company_events` retains the existing background/direct-indirect selection and payload (including no new relevance metadata in digest inputs).

`company_event_page` uses those same direct/indirect matches, retains legacy directly linked source events used elsewhere on the company page, deduplicates raw/normalized members, sorts, then paginates. It returns reasons, dates and bounded coverage, including absent exposure profiles. Existing indexed/public/observed eligibility for indirect evidence stays in place. Direct links are matched without case sensitivity.

All three Assistant entry points now use this reader:

- `research.event_relevance`
- `research.events` with a company symbol
- `research.company_sections` with the events section (previously overwrote indirect matches with a direct-only query)

Keep original source URLs/document IDs/dates. Existing text excerpts become citable delivered evidence. Retrieval itself makes no model calls. The canonical company context continues using the same underlying matching logic and existing limits.

`research.events` without a symbol still searches broader stored events; add a bounded optional literal headline/details query (120 characters), existing date filters and pagination. This has no three-factor gate. A headline query and company symbol are mutually exclusive to avoid silently ignoring either scope. Company/document tools supply context for the model's own analysis.

Prompt explicitly separates stored links from effects the model infers from broader geopolitical/macro evidence. Require citations, conditions and unknowns; never label possible effects as measured impacts or guaranteed returns.

### Coverage limits

The existing indirect candidate cap is 1,000; direct candidate retrieval is bounded at the same count. Cursor pagination covers matched candidates in that scan, not an unlimited archive. Coverage says `bounded_scan`; an empty page must not be claimed as "no relevant events anywhere." Indirect matching defaults to its existing 90-day window when no start is provided; legacy direct rows retain stored-history access unless dates constrain it. No new indexes/embedding pipeline, external news fetch or new model-generated exposure profiles.

## Verification and commands

Offline tests exercise real database exceptions, missing/draft/foreign IPS ownership, rejected allocation rendering, matching-before-pagination, all three Assistant tools, citations/excerpts, legacy direct sources and broad geopolitical keyword retrieval. Existing tool-loop/research suites passed (59 tests). IPS/compliance/workstation/canonical-context integration suites passed (52 tests, including the focused fixtures); the final targeted scope/event/IPS run passed 9 tests. `git diff --check` passed.

A temporary read-only Oracle process loaded just the changed IPS/event functions; it did not change deployed files or stored data. Actual PostgreSQL division-by-zero recovery left the transaction usable and returned `BREACH` with 10 checks and 3 unevaluated checks. Existing stored LUCK data returned 23 matches, including 2 indirect matches, retaining both old company-page matches. Another stored company returned 3 direct matches. No model calls.

No new dependencies or schema migrations. Existing API setup:

```sh
cd apps/api
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

Focused and integration checks (use an isolated test database):

```sh
cd apps/api
DATABASE_URL='sqlite+pysqlite:///:memory:' EMBEDDING_BACKEND=hash .venv/bin/python -m pytest app/tests/test_assistant_scope_fixes.py app/tests/test_compliance_service.py app/tests/test_workstation_api.py app/tests/test_workstation_extended.py app/tests/test_phase7a_canonical_context.py -q
DATABASE_URL='sqlite+pysqlite:///:memory:' EMBEDDING_BACKEND=hash .venv/bin/python -m pytest app/tests/test_phase8_phase1_read_tools.py app/tests/test_phase8_phase2_tool_loop.py app/tests/test_research_intelligence.py -q
```

Migration commands: none for this patch. No seed/backfill required; tests use explicit offline fixtures and live validation reads existing records.
