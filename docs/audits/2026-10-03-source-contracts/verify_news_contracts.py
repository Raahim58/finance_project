"""Read-only bounded source audit; run inside the deployed API container."""
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from app.ingestion.evidence_catalog import SOURCE_SPECS, build_pass1_registry

registry = build_pass1_registry()
requested = set(sys.argv[1:])
for spec in SOURCE_SPECS:
    if spec.key not in requested:
        continue
    started = time.monotonic()
    source = registry.get(spec.key)
    row = dict(source_key=spec.key, checked_at=datetime.now(UTC).isoformat(),
               discovery_url=spec.discovery_url, discovery_method=spec.discovery_method,
               configured_enabled=spec.enabled, poll_seconds=spec.poll_seconds,
               discovery_requests=[], samples=[], discovered=0)
    original = getattr(source, 'fetcher', None)
    if original:
        def capture(url, **kwargs):
            entry = {'requested_url':url, 'method':kwargs.get('method', 'GET'),
                     'params':kwargs.get('params'), 'data':kwargs.get('data')}
            row['discovery_requests'].append(entry)
            try:
                result = original(url, **kwargs)
                content, final_url, content_type, headers = result
                entry.update(final_url=final_url, content_type=content_type,
                             bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
                return result
            except Exception as exc:
                entry['error_type'] = type(exc).__name__
                if getattr(exc, 'response', None) is not None:
                    entry['http_status'] = exc.response.status_code
                raise
        source.fetcher = capture
    try:
        batch = source.discover_since({}, 2)
        row['discovered'] = len(batch.candidates)
        row['next_cursor'] = dict(batch.next_cursor)
        if original:
            source.fetcher = original
        for candidate in batch.candidates[:2]:
            sample = dict(headline=candidate.headline, url=candidate.observed_url,
                          discovery_published_at=candidate.published_at,
                          discovery_metadata=dict(candidate.metadata))
            row['samples'].append(sample)
            try:
                raw = source.fetch(candidate)
                parsed = source.normalize(raw)
                body = parsed.body
                sample.update(final_url=raw.final_url, canonical_url=parsed.canonical_url,
                              raw_bytes=len(raw.content), raw_sha256=hashlib.sha256(raw.content).hexdigest(),
                              content_type=raw.content_type, title=parsed.title,
                              published_at=parsed.published_at, parser_method=parsed.parser_method,
                              extraction_quality=parsed.extraction_quality,
                              body_chars=len(body), body_words=len(body.split()),
                              body_sha256=parsed.body_sha256,
                              body_excerpt=body[:250], body_tail_excerpt=body[-150:],
                              thin_body=len(body.split())<100,
                              publication_missing=parsed.published_at is None,
                              paywall_markers=[phrase for phrase in ['subscribe to read','subscriber-only','premium content','sign in to continue','purchase a subscription'] if phrase in body.lower()])
            except Exception as exc:
                sample['error_type'] = type(exc).__name__
                sample['error'] = str(exc)[:400]
                if getattr(exc, 'response', None) is not None:
                    sample['http_status'] = exc.response.status_code
    except Exception as exc:
        row['error_type'] = type(exc).__name__
        row['error'] = str(exc)[:400]
        if getattr(exc, 'response', None) is not None:
            row['http_status'] = exc.response.status_code
    row['elapsed_seconds'] = round(time.monotonic()-started, 2)
    row['database_writes'] = 0
    row['queue_writes'] = 0
    print(json.dumps(row, default=str), flush=True)
