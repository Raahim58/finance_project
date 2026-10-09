# Overview workspace

`/dashboard` uses the same Inter typography, near-white surfaces, and gray rules as
the other workspaces. The shared fixed header retains search, global portfolio
selection, and notifications. See `docs/design/UI_CONSISTENCY_AUDIT.md` for the
current layout and verification commands.

## Data contract

| Module | Backend source |
| --- | --- |
| Snapshot and ranked price/volume movers | `GET /market/overview` |
| Market session, stale/demo state | `GET /market/freshness` |
| Breadth | Sum database-returned sector counts for the snapshot session only |
| Material events and original evidence | `GET /research/event-feed` |
| Macro assessment and dated observations | `GET /macro/regime` |
| Portfolio list, names and source metadata | `GET /portfolios` |
| Value, day change, holdings and cash | `GET /portfolios/{id}/summary` |
| Cumulative time-weighted return | `GET /portfolios/{id}/performance?limit=500` |
| Active monitoring exceptions | `GET /monitoring/alerts?portfolio_id={id}&status=active` |
| Mandate status | `GET /portfolios/{id}/ips/compliance` |
| Potentially affected portfolio weight | `GET /portfolios/{id}/event-intelligence` |
| Company search | `GET /market/companies?q=…` |
| Account initials | `GET /auth/me` |

No client-side financial fixtures, invented narratives, AI generation on page load,
or database/schema changes are introduced. UI labels and design tokens are static;
financial values, identifiers, sources, dates, rankings and assessments are dynamic.

## Assumptions and missing data

- The backend default active portfolio is the initial scope. Without one, the user
  chooses explicitly. The Overview selector changes this page's view only; it does
  not modify the global default portfolio or holdings.
- Sections load independently. Failed requests, absent observations and observed
  zeros are distinct. Switching portfolios discards responses from the previous scope.
- Breadth uses the snapshot date; no cross-session aggregation is allowed.
- Performance uses backend percentage points directly, preserving null gaps. The
  latest observation supplies the headline TWR; it is not relabeled as PnL or CAGR.
  The available window is at most 500 ledger observations, not an inception claim.
- Cash weights and aggregate event exposure are unavailable when valuation is incomplete.
- Monitoring warnings do not imply an IPS breach. Mandate state comes from the
  compliance response and retains the not-evaluated state.
- Macro directions and commentary come from the regime response, with dates shown
  per series. No unsourced market narrative is generated.
- Events display original citation metadata and use the existing evidence/page drawer.
- Old dashboard widget-layout storage is not applied to this fixed page composition.

## Run and verify

Use the repository's existing API/database setup in `README.md`, then:

```sh
cd apps/web
npm install
npm run dev -- --hostname 127.0.0.1
# Open http://127.0.0.1:3000/dashboard
npm run typecheck
npm test -- lib/overview.test.ts components/overview/OverviewPage.test.tsx
E2E_BASE_URL=http://127.0.0.1:3000 npx playwright test e2e/overview.spec.ts
```

No migration or new seed is needed. Missing backend data stays visibly missing.
Existing database migrations, if setting up a fresh API, use `alembic upgrade head`.
