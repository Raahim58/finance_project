# Live UI corrections

Applied the Apple design skill source at https://raw.githubusercontent.com/dickwu/apple-design-skill/main/SKILL.md and its accessibility, typography, layout, color, desktop/cross-platform and navigation references. Web principles are applied; this is not a native macOS interface.

Normal Portfolios navigation now opens the actual globally selected, non-archived, user-owned portfolio directly. The intermediate portfolio library was removed. With no default, the entry point offers explicit selection/creation instead of silently choosing the first portfolio.

The global portfolio selector and settings control occupy only the top-right control group. Page content no longer waits beneath a full-width global header. Portfolio workspaces use one navigation strip, with no duplicate local portfolio picker. Ask and chat history appear once per desktop context toolbar; the separate sidebar opener and desktop floating duplicate were removed. Mobile retains accessible navigation and an Assistant launcher.

Markets no longer has the repeated Markets title, Markets/Portfolios/Watchlist strip, or the middle view dropdown. A plain active-view title and adjacent search button replace the dropdown; the left navigation remains the view switch. Search matches stored symbols, names and sectors. No prices or financial results were fabricated.

Typography uses one system UI family and a consistent hierarchy. Headings use 34px desktop styles, primary content 14px, tabular data 13–14px and source metadata 12px where possible. Existing numerical calculation semantics are unchanged.

Evidence documents open in a central reader, with document navigation on the left and source context on the right. Original retained page text is separate from verified financial amounts. Changing documents invalidates delayed page responses, so text from one source cannot appear under another title. Portfolio report catalogs query actual held issuers rather than filtering the latest global 50 files. Data resources load independently. Global company filters load issuer-specific retained documents.

Research requests `order=published`; the backend applies publication ordering before pagination. The legacy default remains added-time ordering for document management. This server change needs API deployment to take effect against the remote database. No schema migration or new ingestion cadence is required.

Validation commands:

```sh
cd apps/web
npm run typecheck
npm test -- --maxWorkers=2
```

```sh
cd apps/api
DATABASE_URL=sqlite+pysqlite:///:memory: EMBEDDING_BACKEND=hash .venv/bin/pytest app/tests/test_document_publication_order.py app/tests/test_rag_api.py -q
```

Deployment was not run: the user requested to handle it. Both API and web changes are present locally. Existing deployment command is `./ops/oracle-deploy`; no new migration is required.
