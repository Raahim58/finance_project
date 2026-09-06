from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import replace
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.ai.providers.base import LLMProvider, ProviderRequestError
from app.core.config import settings
from app.reasoning.contracts import (
    MarketCandidateSet,
    ModelAnswer,
    ReasoningRequest,
    ReasoningResult,
    ReasoningInvocation,
    SectorCandidateSet,
)
from app.reasoning.validation import parse_model_answer, validate_model_answer


class _State(TypedDict, total=False):
    request: ReasoningRequest
    sector_candidates: list[str]
    selected_candidates: list[str]
    deep_context: dict[str, object]
    raw_answer: str
    parsed_answer: ModelAnswer
    validation_errors: list[str]
    repaired: bool
    unavailable_reason: str
    trace: list[dict[str, object]]


def _json(raw: str) -> dict[str, object] | None:
    try:
        value = json.loads(raw.strip())
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


class ReasoningEngine:
    """Stateless Phase 8 graph. Application data remains outside LangGraph state."""

    def __init__(
        self,
        provider: LLMProvider,
        api_key: str,
        model: str | None,
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.input_tokens = 0
        self.output_tokens = 0
        self.model_calls = 0
        self.invocations: list[ReasoningInvocation] = []
        self.graph = self._build_graph()

    async def _chat(
        self, operation: str, system: str, payload: dict[str, object]
    ):
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, default=str)},
        ]
        serialized = json.dumps(messages, separators=(",", ":"), ensure_ascii=False)
        input_bytes = len(serialized.encode("utf-8"))
        input_sha256 = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        started = time.perf_counter()
        self.model_calls += 1
        try:
            response = await self.provider.chat(self.api_key, messages, self.model)
        except Exception as exc:
            provider_error = exc if isinstance(exc, ProviderRequestError) else None
            safe_error_message = (
                str(exc) if provider_error is None else provider_error.provider_message
            )
            self.invocations.append(
                ReasoningInvocation(
                    operation=operation,
                    provider=self.provider.name,
                    model=self.model or self.provider.default_model,
                    status="provider_error" if provider_error else "error",
                    input_bytes=input_bytes,
                    input_sha256=input_sha256,
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    http_status=None
                    if provider_error is None
                    else provider_error.status_code,
                    error_type=type(exc).__name__
                    if provider_error is None
                    else provider_error.error_type,
                    error_message=None
                    if safe_error_message is None
                    else safe_error_message[:2000],
                    provider_request_id=None
                    if provider_error is None
                    else provider_error.request_id,
                )
            )
            raise
        self.input_tokens += response.input_tokens or 0
        self.output_tokens += response.output_tokens or 0
        self.invocations.append(
            ReasoningInvocation(
                operation=operation,
                provider=response.provider,
                model=response.model,
                status="success",
                input_bytes=input_bytes,
                input_sha256=input_sha256,
                latency_ms=round((time.perf_counter() - started) * 1000),
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                response_excerpt=response.content[:12_000],
            )
        )
        return response

    async def _discover_sector(
        self, sector: str, records: list[dict[str, object]], question: str
    ) -> tuple[str, list[str], str | None]:
        allowed = {str(row["instrument_id"]) for row in records}
        response = await self._chat(
            "sector_discovery",
            "You perform CFA-style peer group analysis within exactly one supplied PSX "
            "sector. Compare only the supplied records, respect missing data, and select "
            "candidates for deeper research. Do not issue Buy, Hold, Reduce, Avoid, or any "
            "final recommendation. Do not change sector membership. Return JSON only as "
            '{"instrument_ids":["server id"]}.',
            {
                "question": question,
                "sector": sector,
                "records": records,
                "maximum_candidates": settings.phase8_sector_candidate_limit,
            },
        )
        try:
            parsed = SectorCandidateSet.model_validate(_json(response.content) or {})
        except Exception as exc:
            return sector, [], type(exc).__name__
        selected = list(dict.fromkeys(parsed.instrument_ids))
        if len(selected) > settings.phase8_sector_candidate_limit or set(selected) - allowed:
            return sector, [], "invalid_sector_candidate_scope"
        return sector, selected, None

    async def _discover(self, state: _State) -> dict[str, object]:
        request = state["request"]
        trace = list(state.get("trace", []))
        if request.mode != "market_wide":
            return {
                "selected_candidates": sorted(request.allowed_instrument_ids),
                "trace": trace,
            }
        if not request.sector_packets:
            return {
                "unavailable_reason": "market_wide_universe_empty",
                "validation_errors": ["No eligible active PSX securities were available."],
                "trace": trace,
            }
        results = await asyncio.gather(
            *[
                self._discover_sector(sector, records, request.question)
                for sector, records in request.sector_packets.items()
            ]
        )
        candidates: list[str] = []
        failed: list[str] = []
        for sector, selected, error in results:
            candidates.extend(selected)
            if error:
                failed.append(sector)
            trace.append(
                {
                    "node": "peer_group_analysis",
                    "sector": sector,
                    "universe_count": len(request.sector_packets[sector]),
                    "candidate_count": len(selected),
                    "status": "completed" if error is None else "invalid",
                }
            )
        candidates = list(dict.fromkeys(candidates))
        if failed:
            return {
                "unavailable_reason": "sector_discovery_invalid",
                "validation_errors": [
                    "Invalid sector discovery output for: " + ", ".join(sorted(failed))
                ],
                "trace": trace,
            }
        if not candidates:
            return {
                "unavailable_reason": "sector_discovery_empty",
                "validation_errors": ["Peer analysis selected no candidates for deep research."],
                "trace": trace,
            }
        return {"sector_candidates": candidates, "trace": trace}

    async def _reduce_candidates(self, state: _State) -> dict[str, object]:
        if state.get("unavailable_reason") or state["request"].mode != "market_wide":
            return {}
        request = state["request"]
        candidates = state.get("sector_candidates", [])
        response = await self._chat(
            "market_candidate_reduction",
            "Select the bounded cross-sector deep-research set from candidates already "
            "chosen by within-sector peer analysis. Consider the supplied portfolio and IPS "
            "context. Do not issue a final recommendation and do not add instruments. Return "
            'JSON only as {"instrument_ids":["server id"]}.',
            {
                "question": request.question,
                "portfolio_id": request.portfolio_id,
                "portfolio_name": request.portfolio_name,
                "candidate_instrument_ids": candidates,
                "portfolio_and_ips_context": request.grounded_context.get(
                    "portfolio_and_ips"
                ),
                "maximum_candidates": settings.phase8_market_deep_candidate_limit,
            },
        )
        try:
            parsed = MarketCandidateSet.model_validate(_json(response.content) or {})
        except Exception as exc:
            return {
                "unavailable_reason": "market_candidate_reduction_invalid",
                "validation_errors": [type(exc).__name__],
            }
        selected = list(dict.fromkeys(parsed.instrument_ids))
        if (
            not selected
            or len(selected) > settings.phase8_market_deep_candidate_limit
            or set(selected) - set(candidates)
        ):
            return {
                "unavailable_reason": "market_candidate_reduction_invalid",
                "validation_errors": ["Deep-research candidates violated the supplied scope."],
            }
        trace = [
            *state.get("trace", []),
            {
                "node": "market_candidate_reduction",
                "input_count": len(candidates),
                "candidate_count": len(selected),
                "status": "completed",
            },
        ]
        return {"selected_candidates": selected, "trace": trace}

    async def _deepen(self, state: _State) -> dict[str, object]:
        if state.get("unavailable_reason"):
            return {}
        request = state["request"]
        selected = state.get("selected_candidates", [])
        if request.deepen_candidates is None or not selected:
            return {"deep_context": {}}
        deep = await request.deepen_candidates(selected)
        return {
            "deep_context": deep,
            "trace": [
                *state.get("trace", []),
                {
                    "node": "canonical_deep_context",
                    "instrument_count": len(selected),
                    "status": "completed",
                },
            ],
        }

    def _effective_request(self, state: _State) -> ReasoningRequest:
        deep = state.get("deep_context", {})
        return replace(
            state["request"],
            allowed_evidence_ids={
                *state["request"].allowed_evidence_ids,
                *set(deep.get("allowed_evidence_ids", [])),
            },
            allowed_numeric_tokens={
                *state["request"].allowed_numeric_tokens,
                *set(deep.get("allowed_numeric_tokens", [])),
            },
        )

    async def _synthesize(self, state: _State) -> dict[str, object]:
        if state.get("unavailable_reason"):
            return {}
        request = self._effective_request(state)
        selected = state.get("selected_candidates", [])
        response = await self._chat(
            "synthesis",
            "You are the semantic investment reasoning layer. Write the complete natural "
            "user-facing answer once in `answer`; the server will display it unchanged. Use "
            "only supplied evidence and exact structured numbers. Focus on the requested "
            "holding or named comparison; for market-wide discovery, recommend only from the "
            "deep-research set. You may conclude Buy/Add, Hold, Reduce, Avoid, or Insufficient "
            "Evidence when asked for advice. Tie any Buy/Add, Hold, Reduce, or Avoid conclusion "
            "to a horizon from the user or confirmed IPS; use Insufficient Evidence when a "
            "portfolio, mandate, horizon, or other core input is unavailable. Treat IPS Required "
            "Return as a hurdle, never an asset forecast. "
            "For a recommendation, the answer must state the thesis, portfolio and IPS fit, "
            "catalysts, principal risks, invalidation conditions, confidence, missing evidence, "
            "and citations to supplied evidence IDs. Disclose missing and stale evidence. Never "
            "claim to run or save a tool, scenario, "
            "optimizer, trade, portfolio change, or IPS change. Return exactly one JSON object "
            "with: answer, recommendation (allowed label or null), confidence (High, Medium, "
            "Low, or null), horizon ({label,source} or null), portfolio_id, instrument_ids, "
            "evidence_ids, freshness_acknowledgements. "
            "The metadata must describe the answer without duplicating its prose.",
            {
                "question": request.question,
                "conversation_history": request.history,
                "portfolio_id": request.portfolio_id,
                "portfolio_name": request.portfolio_name,
                "mode": request.mode,
                "selected_instrument_ids": selected,
                "grounded_context": request.grounded_context,
                "deep_context": state.get("deep_context", {}),
                "allowed_evidence_ids": sorted(request.allowed_evidence_ids),
                "allowed_instrument_ids": sorted(request.allowed_instrument_ids),
                "freshness_warnings": request.freshness_warnings,
                "allowed_numeric_tokens": sorted(request.allowed_numeric_tokens),
            },
        )
        return {
            "raw_answer": response.content,
            "trace": [
                *state.get("trace", []),
                {"node": "llm_synthesis", "status": "completed"},
            ],
        }

    async def _validate(self, state: _State) -> dict[str, object]:
        if state.get("unavailable_reason"):
            return {}
        parsed, errors = parse_model_answer(state.get("raw_answer", ""))
        if parsed is not None:
            errors.extend(validate_model_answer(parsed, self._effective_request(state)))
        result: dict[str, object] = {"validation_errors": errors}
        if parsed is not None:
            result["parsed_answer"] = parsed
        return result

    async def _repair(self, state: _State) -> dict[str, object]:
        request = self._effective_request(state)
        response = await self._chat(
            "mechanical_repair",
            "Repair only the mechanically invalid fields listed in validation_errors. "
            "Preserve the original answer and recommendation unless a listed mechanical error "
            "requires changing them. Do not introduce new facts or evidence. Return the same "
            "single JSON object schema and nothing else.",
            {
                "original_response": state.get("raw_answer"),
                "validation_errors": state.get("validation_errors", []),
                "portfolio_id": request.portfolio_id,
                "allowed_instrument_ids": sorted(request.allowed_instrument_ids),
                "allowed_evidence_ids": sorted(request.allowed_evidence_ids),
                "freshness_warnings": request.freshness_warnings,
            },
        )
        parsed, errors = parse_model_answer(response.content)
        if parsed is not None:
            errors.extend(validate_model_answer(parsed, request))
        result: dict[str, object] = {
            "raw_answer": response.content,
            "validation_errors": errors,
            "repaired": True,
            "trace": [
                *state.get("trace", []),
                {"node": "mechanical_repair", "status": "completed"},
            ],
        }
        if parsed is not None:
            result["parsed_answer"] = parsed
        if errors:
            result["unavailable_reason"] = "structurally_invalid_after_repair"
        return result

    @staticmethod
    def _after_discover(state: _State) -> str:
        if state.get("unavailable_reason"):
            return "finish"
        return "reduce" if state["request"].mode == "market_wide" else "deepen"

    @staticmethod
    def _after_validate(state: _State) -> str:
        return "repair" if state.get("validation_errors") else "finish"

    def _build_graph(self):
        graph = StateGraph(_State)
        graph.add_node("discover", self._discover)
        graph.add_node("reduce", self._reduce_candidates)
        graph.add_node("deepen", self._deepen)
        graph.add_node("synthesize", self._synthesize)
        graph.add_node("validate", self._validate)
        graph.add_node("repair", self._repair)
        graph.add_node("finish", lambda _state: {})
        graph.add_edge(START, "discover")
        graph.add_conditional_edges(
            "discover",
            self._after_discover,
            {"reduce": "reduce", "deepen": "deepen", "finish": "finish"},
        )
        graph.add_edge("reduce", "deepen")
        graph.add_edge("deepen", "synthesize")
        graph.add_edge("synthesize", "validate")
        graph.add_conditional_edges(
            "validate", self._after_validate, {"repair": "repair", "finish": "finish"}
        )
        graph.add_edge("repair", "finish")
        graph.add_edge("finish", END)
        return graph.compile()

    async def run(self, request: ReasoningRequest) -> ReasoningResult:
        try:
            state = await self.graph.ainvoke({"request": request, "trace": []})
        except Exception as exc:
            reason = f"provider_or_graph_error:{type(exc).__name__}: {exc}"
            state = {
                "unavailable_reason": reason,
                "validation_errors": [],
                "trace": [{"node": "reasoning_error", "status": "unavailable", "reason": reason}],
            }
        parsed = state.get("parsed_answer")
        if parsed is not None and not state.get("validation_errors"):
            return ReasoningResult(
                answer=parsed.answer,
                recommendation=parsed.recommendation,
                confidence=parsed.confidence,
                horizon=parsed.horizon,
                evidence_ids=parsed.evidence_ids,
                instrument_ids=parsed.instrument_ids,
                status="grounded",
                provider=self.provider.name,
                model=self.model or self.provider.default_model,
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                model_calls=self.model_calls,
                repaired=bool(state.get("repaired")),
                trace=state.get("trace", []),
                invocations=list(self.invocations),
            )
        fallback = str(
            request.grounded_context.get("deterministic_fallback")
            or "The grounded facts are available, but recommendation synthesis could not be completed."
        )
        return ReasoningResult(
            answer="Recommendation Synthesis Unavailable\n\n" + fallback,
            recommendation=None,
            confidence=None,
            horizon=None,
            evidence_ids=[],
            instrument_ids=[],
            status="unavailable",
            provider=self.provider.name,
            model=self.model or self.provider.default_model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            model_calls=self.model_calls,
            failure_reason=str(
                state.get("unavailable_reason")
                or "; ".join(state.get("validation_errors", []))
                or "unknown_reasoning_failure"
            ),
            validation_errors=list(state.get("validation_errors", [])),
            repaired=bool(state.get("repaired")),
            trace=state.get("trace", []),
            invocations=list(self.invocations),
        )
