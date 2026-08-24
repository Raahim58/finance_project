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
    definitions = json.loads(args.cases.read_text())
    cases = [
        {**definition, "query": query}
        for definition in definitions
        for query in [definition["query"], *definition.get("query_variants", [])]
    ]
    passed = 0
    positive_total = 0
    positive_passed = 0
    negative_total = 0
    negative_passed = 0
    violations = 0
    rows: list[dict[str, object]] = []
    with SessionLocal() as db:
        for case in cases:
            request = RagSearchRequest(
                query=case["query"],
                symbols=case.get("symbols"),
                document_types=case.get("document_types"),
                time_horizon=case.get("time_horizon"),
                limit=args.top_k,
            )
            response = search_rag(db, None, request)
            expected_symbols = {value.upper() for value in case.get("symbols", [])}
            expected_types = set(case.get("document_types", []))
            titles = [chunk.citation.title for chunk in response.chunks]
            expected_status = case.get("expected_status", "ok")
            expected_title = case.get("expected_title_contains")
            matched = response.status == expected_status and (
                expected_title is None
                or any(expected_title.casefold() in title.casefold() for title in titles)
            )
            is_negative = expected_status == "insufficient_evidence"
            negative_total += int(is_negative)
            negative_passed += int(is_negative and matched)
            positive_total += int(not is_negative)
            positive_passed += int(not is_negative and matched)
            entity_violation = any(
                expected_symbols and (chunk.symbol or "").upper() not in expected_symbols
                for chunk in response.chunks
            )
            type_violation = any(
                expected_types and chunk.document_type not in expected_types
                for chunk in response.chunks
            )
            passed += int(matched)
            violations += int(entity_violation or type_violation)
            rows.append({
                "query": case["query"],
                "category": case.get("category", "uncategorized"),
                "passed": matched,
                "expected_status": expected_status,
                "status": response.status,
                "returned_titles": titles,
                "returned_scores": [
                    {
                        "semantic": chunk.semantic_score,
                        "lexical": chunk.lexical_score,
                        "rrf": chunk.rrf_score,
                    }
                    for chunk in response.chunks
                ],
                "entity_or_filter_violation": entity_violation or type_violation,
            })
    recall = passed / len(cases) if cases else 0.0
    positive_recall = positive_passed / positive_total if positive_total else 0.0
    negative_rejection = negative_passed / negative_total if negative_total else 1.0
    print(json.dumps({
        "cases": len(cases),
        "passed": passed,
        "recall_at_k": round(recall, 4),
        "positive_recall_at_k": round(positive_recall, 4),
        "negative_rejection_rate": round(negative_rejection, 4),
        "violations": violations,
        "results": rows,
    }, indent=2))
    if positive_recall < args.minimum_recall or negative_rejection < 1.0 or violations:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
