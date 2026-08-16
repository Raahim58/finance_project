# Global Evidence Pass 4: breadth canary

This round wires Tier-1/global reporting, geopolitical reporting, and
representative specialist-sector feeds through the existing generic RSS/Atom and
HTML-listing adapters. It adds no browser automation or publisher-specific
article parser. Every source remains behind the shared Pass 4 discovery, fetch,
selection, storage, and concurrency ceilings.

## Source scope

Tier-1 and geopolitical contracts:

| Source | Discovery | Full article smoke | State |
| --- | --- | --- | --- |
| Reuters | listing/sitemap returned HTTP 401 | unavailable | dormant |
| Bloomberg Markets | public RSS | article HTTP 403 | dormant/metadata-only |
| Financial Times | public RSS | article HTTP 403 | dormant/metadata-only |
| Associated Press | public world listing | 2/2 parsed | enabled |
| New York Times | public World RSS | article HTTP 403 | dormant/metadata-only |
| BBC World | public RSS | 2/2 parsed | enabled |
| Guardian World | public RSS | 2/2 parsed | enabled |
| CNBC Top News | public RSS | 2/2 parsed | enabled |
| Nikkei Asia | public RSS | 2/2 parsed, limited body depth | enabled/limited |
| Al Jazeera | public RSS hostname failed DNS | unavailable | dormant |
| Zeteo | public site feed | 2/2 parsed | enabled |

Specialist contracts:

| Coverage | Sources | Live result |
| --- | --- | --- |
| semiconductors / AI infrastructure | Semiconductor Engineering, EE Times | both 2/2 parsed |
| EV / battery / lithium developments | Electrive | 2/2 parsed |
| direct mining / lithium | MINING.COM | public feed HTTP 403; dormant |
| oil / LNG / gas | LNG Prime, plus existing EIA/OPEC official sources | LNG Prime 2/2 parsed |
| shipping / freight | gCaptain, FreightWaves | both 2/2 parsed |
| cotton | Cotton Grower | 2/2 parsed |
| fertilizer | Fertilizer Daily | 2/2 parsed |
| coal | Coal Age | 2/2 parsed |
| palm oil | Malaysian Palm Oil Council | 2/2 parsed |
| steel / industrial metals | MetalMiner, Steel Market Update | both 2/2 parsed |

The smoke command performs no Postgres, Redis, or Celery writes and hard-caps
the sample to one or two candidates per source:

```bash
python -u -m app.jobs.evidence_source_smoke \
  --group pass4_breadth \
  --limit 2 \
  --fetch
```

## Enable and run

Set this in `apps/api/.env`:

```dotenv
EVIDENCE_PASS4_BREADTH_ENABLED=true
```

All evidence workers and the evidence scheduler must be restarted once after
deploying this code because each process builds its source registry at import
time. No migration is required. On macOS/Python 3.13 retain the existing threads
pool and concurrency values.

After restarting the workers, run the existing continuous scheduler:

```bash
EVIDENCE_ENABLED=true python -u -m app.jobs.evidence_scheduler
```

Monitor durable progress with:

```bash
python -m app.jobs.evidence_status --watch 10
```

The breadth and official groups use a single global Pass 4 budget. Per-source
breadth limits are deliberately small: Tier-1 sources fetch at most 6-8 items per
UTC day, and specialist sources fetch at most 5-6. Duplicate rate alone never
disables a source.
