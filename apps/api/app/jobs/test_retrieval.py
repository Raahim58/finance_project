import argparse

from app.db.session import SessionLocal
from app.schemas.rag import RagSearchRequest
from app.services.rag_service import search_rag


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local RAG retrieval smoke test.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--symbol", action="append", default=None)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    with SessionLocal() as db:
        result = search_rag(
            db,
            None,
            RagSearchRequest(query=args.query, symbols=args.symbol, limit=args.limit),
        )

    print(f"Found {len(result.chunks)} chunks.")
    for index, chunk in enumerate(result.chunks, start=1):
        print(f"[{index}] score={chunk.score} title={chunk.citation.title} page={chunk.page_number}")
        print(chunk.citation.quote_snippet)


if __name__ == "__main__":
    main()
