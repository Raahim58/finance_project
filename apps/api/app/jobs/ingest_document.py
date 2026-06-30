import argparse
from datetime import date
from pathlib import Path

from app.db.session import SessionLocal
from app.services.rag_service import create_document_from_pages, parse_document_content


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a local company document into RAG tables.")
    parser.add_argument("--file", required=True, help="Path to a text, Markdown, or PDF file.")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--sector", default=None)
    parser.add_argument("--type", required=True, dest="document_type")
    parser.add_argument("--title", default=None)
    parser.add_argument("--fiscal-year", type=int, default=None)
    parser.add_argument("--quarter", default=None)
    parser.add_argument("--source-name", default="local")
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--published-date", type=date.fromisoformat, default=None)
    args = parser.parse_args()

    path = Path(args.file)
    content = path.read_bytes()
    pages = parse_document_content(path.name, content)
    with SessionLocal() as db:
        document = create_document_from_pages(
            db,
            pages,
            title=args.title or path.stem,
            document_type=args.document_type,
            symbol=args.symbol,
            sector=args.sector,
            fiscal_year=args.fiscal_year,
            quarter=args.quarter,
            source_name=args.source_name,
            source_url=args.source_url,
            local_file_path=str(path),
            published_date=args.published_date,
        )
    print(f"Ingested document {document.id}: {document.title}")


if __name__ == "__main__":
    main()
