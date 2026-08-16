"""Bounded, database-free discovery/fetch smoke for configured evidence sources."""

from __future__ import annotations

import argparse
import json

from app.ingestion.evidence_catalog import SOURCE_SPECS, build_pass1_registry


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke evidence sources without writing to Postgres, Redis, or Celery"
    )
    parser.add_argument("--group", default="pass4_breadth")
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--include-dormant", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 2:
        parser.error("--limit must be 1 or 2")

    requested = {item.strip() for item in args.source if item.strip()}
    specs = [
        spec
        for spec in SOURCE_SPECS
        if spec.canary_group == args.group
        and (not requested or spec.key in requested)
        and (args.include_dormant or not spec.fallback.startswith("dormant:"))
    ]
    missing = requested - {spec.key for spec in specs}
    if missing:
        parser.error(f"Unknown, out-of-group, or dormant sources: {', '.join(sorted(missing))}")

    registry = build_pass1_registry()
    results: list[dict[str, object]] = []
    for spec in specs:
        source = registry.get(spec.key)
        row: dict[str, object] = {
            "source_key": spec.key,
            "discovery_url": spec.discovery_url,
            "discovered": 0,
            "fetched": 0,
            "parsed": 0,
            "samples": [],
        }
        try:
            candidates = source.discover_since({}, args.limit).candidates[: args.limit]
            row["discovered"] = len(candidates)
            samples: list[dict[str, object]] = []
            for candidate in candidates:
                sample: dict[str, object] = {
                    "headline": candidate.headline,
                    "url": candidate.observed_url,
                }
                if args.fetch:
                    try:
                        raw = source.fetch(candidate)
                        row["fetched"] = int(row["fetched"]) + 1
                        parsed = source.normalize(raw)
                        row["parsed"] = int(row["parsed"]) + 1
                        sample["content_type"] = raw.content_type
                        sample["bytes"] = len(raw.content)
                        sample["body_chars"] = len(parsed.body)
                    except Exception as exc:  # smoke output must retain per-item failures
                        sample["fetch_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
                samples.append(sample)
            row["samples"] = samples
        except Exception as exc:
            row["discovery_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        results.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)

    summary = {
        "sources": len(results),
        "discovery_ok": sum("discovery_error" not in row and int(row["discovered"]) > 0 for row in results),
        "fetch_ok": sum(int(row["fetched"]) > 0 for row in results),
        "parse_ok": sum(int(row["parsed"]) > 0 for row in results),
        "database_writes": 0,
        "queue_writes": 0,
    }
    print(json.dumps({"summary": summary}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
