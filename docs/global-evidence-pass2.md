# Global Evidence Pass 2

Pass 2 operationalizes the Pass 1 pipeline without sharing Phase 2 queues.

```text
evidence_discovery (4)
    -> evidence_fetch (16)
    -> evidence_parse (6) or evidence_pdf (2)
    -> evidence_index (4)

historical_hydrate (2, low priority)
```

Redis carries candidate/request IDs, never article bodies. Postgres stores source
cursors, health, candidates, leases, stage state, refresh requests, events and
selection decisions. A shared bounded `.evidence-spool` under
`SOURCE_ARTIFACT_ROOT` holds raw and parsed content temporarily between stages. It
is deleted after selection/rejection/duplication and pruned after the configured
retention window.

## Live behavior and recovery

The dedicated scheduler polls due enabled sources, observes queue targets, reserves
rows before publishing and reconstructs expired leases. Live tasks use Redis priority
`0`; historical tasks use priority `8`. Worker prefetch remains one, so live tasks
cannot be hidden behind large worker reservations. Repeated discovery failures open
a per-source circuit using `EvidenceSourceState.next_poll_at`; successful discovery
resets it.

Candidate metadata older than `EVIDENCE_CANDIDATE_RETENTION_DAYS` is marked expired.
URLs and hashes in terminal rows remain available for rediscovery prevention. Failed
stages use bounded exponential retry timestamps. Broker publication failures remain
visible on the durable row and can be reconstructed.

## Historical policy

Holdings, benchmark instruments, promoted screening candidates and explicitly deep
instruments produce at most one initial low-priority hydration request. Pass 3 now
wraps these requests in durable 12-month PSX/deep-company and 90-day news presets.
The free GDELT DOC window remains capped at 90 days, so 12-month deep-company work
uses the existing PSX source for official metadata/documents and does not pretend to
provide 12 months of general publisher news. It does not trigger unbounded PDF or
article ingestion.

## APIs

Authenticated endpoints:

- `POST /ingestion/evidence/refresh` — bounded symbol/topic/sector/query refresh.
- `POST /ingestion/evidence/historical` — bounded low-priority symbol hydration.
- `GET /ingestion/evidence/requests` — ownership-scoped request status.
- `GET /ingestion/evidence/operations` — source health, stage backlog, dedupe,
  extraction and retained-doc/story statistics.

The API records a request before publishing it. A Redis outage therefore leaves a
queued request that the scheduler can republish. These endpoints create narrative
evidence only; they never create exact market, portfolio or macro observations from
article text.

## Intentional later work

Playwright fallback, broader source coverage, multilingual normalization, and
source-specific extraction refinements remain later-pass work. DNS-rebinding
protection beyond literal/private redirect checks requires deployment-level egress
controls. Product Phase 4–6 retrieval, entity intelligence, event reasoning, and
final assistant synthesis remain out of scope.
