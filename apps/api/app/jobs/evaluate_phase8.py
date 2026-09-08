"""Run deterministic Phase 8 quality fixtures without network or paid model calls."""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from app.reasoning.allocation import AllocationProposal, calculate_allocation
from app.services.assistant_diagnostics import SAFE_FIELDS


CASES = Path(__file__).resolve().parents[1] / "evaluation" / "phase8_offline.json"


def evaluate(path: Path = CASES) -> dict[str, object]:
    cases = json.loads(path.read_text())
    failures: list[dict[str, object]] = []
    labels: Counter[str] = Counter()
    for case in cases:
        labels.update(case["labels"])
        expected = case["expected"]
        if "proposal" not in case:
            forbidden = set(expected["safe_fields_exclude"])
            if forbidden & SAFE_FIELDS:
                failures.append({"id": case["id"], "reason": "diagnostic_allowlist_leak"})
            continue
        proposal = AllocationProposal.model_validate(case["proposal"])
        result = calculate_allocation(
            proposal, case["positions"], case["cash"], case["instruments"]
        )
        if result["accepted"] != expected["accepted"]:
            failures.append({"id": case["id"], "reason": "acceptance_mismatch"})
        if "proposed_cash" in expected and expected["proposed_cash"] != result.get("proposed_cash"):
            failures.append({"id": case["id"], "reason": "cash_mismatch"})
        if expected.get("error") and expected["error"] not in result["errors"]:
            failures.append({"id": case["id"], "reason": "missing_expected_error"})
    return {
        "cases": len(cases),
        "passed": len(cases) - len(failures),
        "failed": failures,
        "label_coverage": dict(labels),
        "provider_calls": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.live:
        if os.environ.get("ALLOW_PAID_PHASE8_BENCHMARKS", "false").lower() != "true":
            parser.error("Live benchmarks are disabled; no paid model calls are authorized")
        parser.error("Live runner is intentionally unimplemented pending explicit benchmark approval")
    result = evaluate(args.cases)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
