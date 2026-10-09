# Portfolio, Quant, Research and oversight UI

Implemented on `ui-updates` using the raster references under `work/ui-proposal/images`. Included: portfolio library, Overview, IPS, Quant, Build (added explicitly later), portfolio Research/Activity, global Research/evidence, Assistant, Monitoring, Recommendations and Activity. Company, Risk, Scenarios and Settings/account were excluded from this pass.

Every financial figure comes from an existing backend response or formatting its returned units. Mockup numbers, fictional frontier points and invented event/source metadata are not used. Missing data renders as `—` or an explicit unavailable state. A retrieved data error is distinct from a confirmed absence. Incomplete valuations cannot establish complete allocation weights. Analytical estimates retain backend method, date, sample and cash/risky-sleeve basis.

The portfolio library selects only an actual user default initially; another portfolio requires selection. IPS changes preserve retained constraints and goal assumptions, show review before explicit immutable confirmation, and do not mutate the current confirmed version while editing. Build uses actual saved allocation weights and explicit comparison/optimization calls. Missing saved objective/method metadata is not invented. A model comparison is not a trade, and proposal saving does not change holdings.

Research uses company-scoped stored documents, indexed page text and selected event evidence. Portfolio research limits documents to its actual holdings. Exact numerical facts are not inferred from retrieved text. Monitoring distinguishes configured rules from evaluation coverage and cannot infer a successful check from an empty alert queue. Recommendations show only recorded impact/check data; unavailable comparison/confidence fields stay blank. Activity merges the dated ledger and audit stream, retains source identity, and provides filters and CSV export.

Assistant is one persistent workspace used both as a sidebar and the full Chat page. Existing threads, run streaming, stop controls, summaries, sources, provider selection and usage remain. Page-local portfolio filters set explicit, path-scoped request context validated against owned portfolios; an All portfolios filter does not silently use the global default. Opening/prefilling a chat or changing scope does not submit a model request.

No schema migration or seed data is needed. Existing database migration command when the database is behind repository head:

```sh
docker compose -f compose.oracle.yml exec -T api alembic upgrade head
```

Local validation:

```sh
cd apps/web
npm ci
npm run typecheck
npm test
```

The local preview on 13000 uses the existing `NEXT_DIST_DIR` option and a backend tunnel. Deployment is web-only, takes the shared Oracle deployment lock, and leaves hourly ingestion and worker topology unchanged. Live browser verification is currently unavailable because the computer-use browser connection is disconnected; automated verification does not establish pixel-perfect visual matching.
