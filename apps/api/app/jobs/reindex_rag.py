import json

from sqlalchemy import select

from app.db.session import SessionLocal
from app.core.config import settings
from app.models.document import DocumentChunk
from app.services.rag_service import embed_text


def main() -> None:
    with SessionLocal() as db:
        chunks = db.scalars(select(DocumentChunk)).all()
        for chunk in chunks:
            vector = embed_text(chunk.chunk_text)
            chunk.embedding_json = json.dumps(vector)
            chunk.embedding_vector = vector if db.bind and db.bind.dialect.name == "postgresql" else json.dumps(vector)
            metadata = json.loads(chunk.metadata_json)
            metadata["embedding_backend"] = settings.embedding_backend
            metadata["embedding_model"] = settings.embedding_model_name if settings.embedding_backend == "sentence_transformers" else "token-hash-v1-development-only"
            chunk.metadata_json = json.dumps(metadata)
            db.add(chunk)
        db.commit()
    print(f"Reindexed {len(chunks)} RAG chunks.")


if __name__ == "__main__":
    main()
