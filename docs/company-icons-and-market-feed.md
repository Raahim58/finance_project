# Company icons and current market evidence

Next.js `.next-*` directories are disposable generated build files, excluded from Git and Docker. Do not delete a directory while its dev server is running. Dev mode compiles routes on first use; production uses precompiled routes.

Company website identity comes from the WEBSITE field of the official PSX issuer profile. The server fetches a favicon through Google's favicon service and stores the small PNG, hash, website, original image URL, PSX profile URL, status and check time in `company_marks`. These are website icons, not verified corporate wordmarks. Missing/16px placeholder icons remain unavailable. No website is guessed from the company name. Browser page requests perform no discovery or ingestion. The logo endpoint reads only stored bytes and supports ETag and one-day browser caching.

This uses database bytes because icons are small (maximum 128 KiB each). Large documents continue using the existing artifact storage. Refreshes retry due companies after 30 days and preserve previously stored images on transient failure. Full initial coverage is attempted, not guaranteed.

Setup and additive migration:

```sh
cd apps/api
alembic upgrade head
python -m app.jobs.company_marks --limit 1000
```

Oracle equivalents:

```sh
docker compose -f compose.oracle.yml exec -T api alembic upgrade head
docker compose -f compose.oracle.yml exec -T api python -m app.jobs.company_marks --limit 1000
```

Run the icon job daily; only companies not checked within 30 days are fetched, with four external fetch workers and serial per-company commits. No demo assets are inserted into observed company coverage. Offline fixtures cover stored-image serving and missing sources.

The market event feed merges classified event records with legacy evidence, removes raw members already covered by a classified record, excludes future events and sorts by occurred date. Browsing considers a bounded candidate set (100 initially, increasing with cursor to 1000); it does not claim exhaustive ranking. News is refreshed with the hourly market view. This reads saved evidence and never silently generates an AI brief. The market digest remains a deterministic summary of the dated market snapshot. Stock table sparklines use one batch read of recent stored daily closes, with observed canonical data preferred and explicit development-only mock fallback rules preserved.
