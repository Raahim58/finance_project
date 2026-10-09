# Workspace UI alignment

The Today-style shared shell header owns screen identity, company search, selected portfolio, notifications and settings. Screen-local tabs/actions render into the same header through `WorkspaceHeader`; the old right-rail-only header override and duplicate Markets title/search/refresh row have been removed. Narrow screens retain horizontal tab scrolling within the header.

Company pages retain the simple sidebar chart of stored daily closes in addition to the technical canvas. The sidebar range is independent; it does not manufacture intraday points or replace daily history with a latest quote.

Markets stock and sector selection replaces Market brief with one closable context rail. Company detail includes the stored quote/date, daily history, retained observed report when available, sector, and selected-portfolio holding weight. Sector detail ranks companies by observed traded volume, includes held companies beyond the first eight rows, and searches names/symbols only within the selected sector. Missing quotes and portfolio valuations are explicit. Weights use market values returned by the owned selected portfolio's summary divided by its returned total value, and are unavailable when valuation is incomplete. No portfolio is inferred when no default exists. Request guards prevent old portfolio responses from replacing newer selections.

Portfolio management uses a flat list with a context rail and inline creation. Existing creation, selection, duplication, comparison, and archive contracts are retained. Archive requires a local confirmation; creation opens the new portfolio's IPS screen. Unrealized PnL is labelled as such rather than total return. Missing valuation/risk data is never presented as zero or clear. No new backend endpoint, schema, migration, financial seed data, LLM calculation, or trade execution was introduced.

Full-page Chat is separated from floating Assistant drawer width rules. Chat keeps saved conversations, context, provider switching, streaming, and evidence. Its duplicated heading/toolbar has been removed. The Ask launcher sits at the desktop navigation foot so it does not cover rail composers; it uses the floating mobile position with extra page clearance. Side-panel and row selection uses text weight only: no selection fill, side stripe, or color change. Header tabs retain their horizontal underline.

Validation/setup:

```sh
cd apps/web
npm ci
npm run dev
npm run typecheck
npm test
npm run build
E2E_BASE_URL=http://127.0.0.1:3000 npm run test:e2e -- workspace-layout.spec.ts overview.spec.ts technical-chart.spec.ts assistant-workspace.spec.ts
```

Use the root README's backend setup for stored data. Existing backend migrations remain `cd apps/api && alembic upgrade head`; this UI change needs no new migration. Browser fixtures are intercepted offline test contracts only, never deployed database facts.
