"""Authenticated redacted diagnostics client; no full-export or payload-print option."""
import argparse
import json
import os
import urllib.request
from collections import Counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--execution-id")
    parser.add_argument("--status", choices=["queued", "running", "completed", "failed", "synthesis_unavailable"])
    parser.add_argument("--aggregate", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("ASSISTANT_ACCESS_TOKEN")
    if not token:
        parser.error("Set ASSISTANT_ACCESS_TOKEN to an authenticated application access token")
    path = "/assistant/diagnostics"
    if args.execution_id:
        from uuid import UUID
        path += "/" + str(UUID(args.execution_id)) + "/export"
    elif args.status:
        path += "?status=" + args.status
    request = urllib.request.Request(args.url.rstrip("/") + path,
                                     headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.load(response)
    if args.aggregate:
        rows = result if isinstance(result, list) else [result]
        result = {"execution_count": len(rows), "outcomes": dict(Counter(row["status"] for row in rows)),
                  "attempt_count": sum(len(row["attempts"]) for row in rows),
                  "unknown_usage_attempts": sum(attempt["metadata"].get("input_tokens") is None
                      for row in rows for attempt in row["attempts"])}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
