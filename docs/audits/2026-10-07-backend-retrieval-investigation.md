# Backend retrieval investigation — 2026-10-07

Investigated the current checkout at `f8e4ee7`. Read the executor, route planner,
research wrapper, RAG ranking, digest projection and citation gate. Ran isolated
SQLite and mocked executor probes against the current code. No paid provider
calls or production database writes were made. Application source is unchanged.

The pasted demo has no execution identifier. These probes establish defects in
the current checkout; they do not establish which deployed revision/configuration
produced each pasted answer. Earlier saved live traces are supporting evidence for
payload growth, not a replay of that exact conversation.

## 1. Alternatives retrieval drops the market screener under the default budget

`assistant_max_tool_iterations` defaults to 12. `_prepare_evidence` first spends
one call on the ownership-checked portfolio summary. The planner receives 11,
reserves four for follow-ups, and admits seven steps. It counts another summary
step while trimming, even though the executor subsequently removes that step.

For an alternatives question, the planner adds one `quant.security` step per
holding before `market.universe`. Required steps at the tail are dropped first.

Mocked executor result for nine explicitly synthetic holdings:

```text
Question: Are there better options in the overall market than what I currently hold?
Route: portfolio_rebalance
Executed: portfolio.summary, ips.compliance, quant.portfolio,
          quant.security(h0), quant.security(h1), quant.security(h2), quant.security(h3)
Dropped: research.search, market.universe, quant.security(h4..h8)
Reserved calls after initial preparation: 7
```

The same planner drops the screener with five holdings. With two holdings it
retains the screener. This is an initial-pass failure: model follow-ups can still
recover the tool, but the backend does not supply the requested market evidence.

Locations: `ai/routing/planner.py:103,157,201,234,251` and
`ai/tool_loop.py:989,1010,1025`.

Existing alternatives tests use allowance **32**, so they do not exercise the
default execution budget (`tests/test_routing.py:240,250`).

Fix direction: account for the already supplied summary before trimming; preserve
the requested universe read before repeated holding detail; batch or reuse
available holding risk data instead of requiring one initial call per holding.
Test the actual executor at the configured limit with five and nine holdings.

## 2. Exact token matching can discard highly relevant dividend evidence

The Python tokenizer does not stem terms. `dividend` and `dividends` do not match.
The semantic admission gate also requires **lexical > 0**, even when semantic
similarity exceeds its threshold. PostgreSQL's English full-text search uses a
different normalization from the subsequent Python term-coverage check.

Isolated fixture, not a real financial announcement:

```text
Stored title: Fixture cash distribution
Stored text: The board declared an interim dividend payable to shareholders.
Explicit symbol filter: FFC

Query dividend                 -> 1 passage
Query dividends                -> 0 passages
Query What about dividends?    -> 0 passages
Forced semantic similarity .99 -> 0 passages, below_relevance_threshold: 1
```

The semantic score was deliberately mocked to isolate the admission rule. This
is not a measurement of the production embedding model's similarity.

Locations: `domain/retrieval.py:64,112`, `services/rag_service.py:763`.

Fix direction: normalize retrieval terms consistently across candidate selection
and reranking; remove conversational filler from search intent; retain explicit
issuer filtering and citation eligibility while calibrating semantic admission.
Test singular/plural forms and short follow-ups through `research.search`.

## 3. A dividend search can report success with only macro evidence

`search_research_evidence` automatically extends dividend/earnings topics with
rates, inflation, FX and geopolitics. `research.search` reports `ok` if *any* lane
returns a passage, even when the company lane has no evidence for the question.

In the same isolated database, added a clearly synthetic news passage:

```text
Pakistan policy rate was discussed in a monetary policy announcement.
```

For `What about dividends?`, explicitly scoped to FFC:

```text
status: ok
company returned: 0
sector returned: 0
broader returned: 1 (Fixture monetary policy)
```

The stored dividend passage still existed. The model received policy commentary
as the successful search result. Lane coverage is present, so the model can notice
the gap, but success does not establish evidence for the requested topic.

Locations: `services/news_retrieval.py:71,77,111` and
`tools/research_tools.py:91`.

Fix direction: make broader context depend on the question's information need;
report primary-topic/issuer evidence as missing or partial when only broader
material survives. Do not force macro expansion into ordinary dividend queries.

## 4. Requested digest sections are ignored in the saved-snapshot path

The prepared-intelligence branch filters `payload.sections`. The current saved
snapshot branch instead projects the entire snapshot and all its sources.

Mocked digest probe with `pipeline_enabled=False`, a current saved snapshot and no
prepared sections:

```text
Requested sections: [dividends]
Returned: financials, unrelated expansion news, corporate_actions,
          source_documents, citation_locations, brief metadata
```

This establishes an actual projection defect. It also applies as a fallback when
prepared intelligence is unavailable. Section selection in the planner does not
by itself guarantee a small model packet.

Locations: `tools/research_tools.py:357,425`.

Saved packet-v2 traces provide separate evidence of size: the LUCK/FFC question's
financials component is 77,778 serialized bytes, locally estimated at 21,098
tokens. The dividend follow-up's financials component is 39,805 bytes, locally
estimated at 9,999 tokens. Component estimates are not additive provider billing
totals. These are saved historical measurements, not new measurements of current
production data.

Fix direction: apply question-specific selection in both digest paths and prune
sources to references retained by that selection. Preserve units, periods,
reporting bases, contradictions and qualifications. Measure actual transmitted
payloads after selection.

## 5. Wrong-source factual claims pass the citation gate

Probe supplied the synthetic answer `LUCK declared a 250% dividend. [[E1]]` with
E1 pointing to a fixture FFC report. The resolver returned:

```text
status: resolved
resolved_count: 1
semantic_verification: not_performed
citation_gate rejection: None
```

The resolver did not corrupt the source mapping in this probe. The model's
incorrect choice of a valid marker passed because the gate checks presence and
identity only. Therefore the pasted wrong-issuer citation cannot be attributed
to retrieval or marker remapping alone without its execution checkpoint.

Locations: `ai/tool_loop.py:817,853,858`.

Fix direction: preserve issuer/metric scope beside evidence; validate structured
numerical claims against their referenced SQL records and source scope. A marker
existence check must not be treated as a source-support check. An issuer check
alone will not establish that a report supports every claim about that issuer.

## Additional freshness weakness

Recent company/document searches are not assigned a date window by the planner.
The RAG score multiplies `freshness_adjustment` (maximum 0.0015) by 0.05 after
adding a constant 0.5. Today versus one year ago changes final score by only about
0.0000651. This effectively makes freshness a tiny tie-breaker; it does not enforce
current evidence. The dedicated market-brief route uses a separate SQL snapshot
and should not be conflated with this document-search path.

Locations: `ai/routing/planner.py:227`, `domain/retrieval.py:176`,
`services/rag_service.py:787`.

## Existing checks

Ran with an explicitly isolated in-memory database and offline hash embeddings:

```sh
DATABASE_URL='sqlite+pysqlite:///:memory:' \
TEST_DATABASE_URL='sqlite+pysqlite:///:memory:' \
EMBEDDING_BACKEND=hash PYTHONPATH=apps/api \
apps/api/.venv/bin/pytest -q \
  apps/api/app/tests/test_routing.py \
  apps/api/app/tests/test_news_retrieval.py \
  apps/api/app/tests/test_company_packet.py
```

Result: **91 passed in 8.13 seconds**. These checks do not cover the failures above.

## Assessment

Keep the existing separation between structured SQL evidence and document text,
and the existing ownership/citation metadata paths. Fix initial evidence priority,
term normalization and question-specific projection before making live search
the next retrieval-quality change. Live search addresses unavailable external
material; the reproduced defects can lose or dilute evidence already stored.
