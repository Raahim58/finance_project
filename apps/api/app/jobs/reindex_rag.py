import json

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.document import DocumentChunk
from app.services.rag_service import embed_text


def main() -> None:
    with SessionLocal() as db:
        chunks = db.scalars(select(DocumentChunk)).all()
        for chunk in chunks:
            chunk.embedding_json = json.dumps(embed_text(chunk.chunk_text))
            db.add(chunk)
        db.commit()
    print(f"Reindexed {len(chunks)} RAG chunks.")


if __name__ == "__main__":
    main()
