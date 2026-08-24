def gate_citations(chunks: list[dict[str, object]], requested_symbols: object) -> list[dict[str, object]]:
    """Keep retrieval-admitted citations matching the explicit symbol scope."""
    allowed = {str(symbol).upper() for symbol in requested_symbols} if isinstance(requested_symbols, list) else set()
    gated: list[dict[str, object]] = []
    for chunk in chunks:
        score = chunk.get("score")
        if not isinstance(score, (int, float)) or chunk.get("citation_eligible") is not True:
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
