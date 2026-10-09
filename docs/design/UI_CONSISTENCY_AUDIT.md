# Shared workspace UI

The latest visual direction follows `work/ui-proposal/ui-samples.zip`: compact
sans-serif typography, near-white columns, quiet gray dividers, and preserved
analytical workflows. Inter is the visual match used for the generated sample
lettering; the sample images do not identify an embedded font. It is bundled
locally with its SIL Open Font License, so rendering needs no font service.

## Layout and tokens

- Desktop left columns begin at the viewport top. The fixed header begins at
  their right edge, using their actual responsive width rather than a guessed
  offset. Stacked mobile panels stay below the mobile header.
- Section tabs are centered within the available header space. Search, global
  portfolio selection, and notifications remain at the right, separated by a rule.
- Header overflow is scrollable on small screens. Nested portfolio tab rows have
  their own space; keyboard focus remains visible.
- Inter is shared by headings, body, controls, and tabular financial values.
  Page/section/subsection headings use 24/18/15px, tables use 12px headers and 13px
  cells; financial headline values retain their hierarchy.
- Canvas: `#FAFBFC`; paper: `#FFFFFF`; secondary surface: `#F3F4F6`;
  dividers: `#E5E8EC`. Semantic positive, negative, and warning colors remain.
- Data failure notices appear in the central analytical column. Missing data
  cannot move a desktop left panel down or be hidden behind it.

Shared styling lives in `apps/web/app/workspace-system.css`. Left panels opt in
with `data-workspace-left-panel`; the shell hook keeps the geometry aligned as
routes, data states, and breakpoints change. Numerical data and workflows are
unchanged.

## Audit and reproduction

The browser audit covers Today, Markets, Company, all eight portfolio sections,
Research, Recommendations, Monitoring, Activity, portfolio management, Settings,
and Chat at 1440px, 1100px, and 390px. It checks horizontal overflow, raised panel
alignment, fixed header position after scroll, visible search controls, typography,
canvas color, and uncaught page errors. The offline fixtures are browser-only;
unsupported endpoints explicitly return unavailable instead of invalid data.

```sh
cd apps/web
npm install
npm run dev -- --hostname 127.0.0.1
npm run typecheck
E2E_BASE_URL=http://127.0.0.1:3000 npx playwright test e2e/workspace-layout.spec.ts
```

Screenshots are generated under `apps/web/test-results/ui-audit/`. The audit also
checks stock/sector selection, company charts, portfolio creation, and opening and
closing Ask. It does not certify live market data or backend availability.

No new migration or seed is required for these UI changes. Fresh backend setup
continues to use the README instructions and `alembic upgrade head`.
