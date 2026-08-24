"""Run the labelled Phase 5 retrieval acceptance set against stored evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.db.session import SessionLocal
from app.schemas.rag import RagSearchRequest
from app.services.rag_service import search_rag


DEFAULT_CASES = Path(__file__).resolve().parents[1] / "evaluation" / "phase5_retrieval.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Phase 5 retrieval against labelled cases.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--minimum-recall", type=float, default=0.80)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())
    passed = 0
    violations = 0
    rows: list[dict[str, object]] = []
    with SessionLocal() as db:
        for case in cases:
            request = RagSearchRequest(
                query=case["query"],
                symbols=case.get("symbols"),
                document_types=case.get("document_types"),
                limit=args.top_k,
            )
            response = search_rag(db, None, request)
            expected_symbols = {value.upper() for value in case.get("symbols", [])}
            expected_types = set(case.get("document_types", []))
            titles = [chunk.citation.title for chunk in response.chunks]
            matched = any(case["expected_title_contains"].casefold() in title.casefold() for title in titles)
            entity_violation = any(
                expected_symbols and (chunk.symbol or "").upper() not in expected_symbols
                for chunk in response.chunks
            )
            type_violation = any(
                expected_types and str(chunk.metadata.get("document_type")) not in expected_types
                for chunk in response.chunks
            )
            passed += int(matched)
            violations += int(entity_violation or type_violation)
            rows.append({
                "query": case["query"],
                "passed": matched,
                "status": response.status,
                "returned_titles": titles,
                "entity_or_filter_violation": entity_violation or type_violation,
            })
    recall = passed / len(cases) if cases else 0.0
    print(json.dumps({
        "cases": len(cases),
        "passed": passed,
        "recall_at_k": round(recall, 4),
        "violations": violations,
        "results": rows,
    }, indent=2))
    if recall < args.minimum_recall or violations:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
