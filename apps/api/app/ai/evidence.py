from app.services.rag_service import MIN_RELEVANCE_SCORE


def gate_citations(chunks: list[dict[str, object]], requested_symbols: object) -> list[dict[str, object]]:
    """Keep only relevant citations that match the explicit symbol scope."""
    allowed = {str(symbol).upper() for symbol in requested_symbols} if isinstance(requested_symbols, list) else set()
    gated: list[dict[str, object]] = []
    for chunk in chunks:
        score = chunk.get("score")
        if not isinstance(score, (int, float)) or score < MIN_RELEVANCE_SCORE:
            continue
        symbol = chunk.get("symbol")
        if allowed and (symbol is None or str(symbol).upper() not in allowed):
            continue
        citation = dict(chunk.get("citation") or {})
        if citation:
            citation["symbol"] = symbol
            citation["relevance_score"] = score
            gated.append(citation)
    return gated
