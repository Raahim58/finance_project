import argparse
import json

from sqlalchemy import select

from app.db.session import SessionLocal
from app.core.config import settings
from app.domain.retrieval import classify_chunk_content, source_tier
from app.models.document import Document, DocumentChunk
from app.services.rag_service import active_embedding_model, embed_texts


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-index RAG chunks with the configured embedding model.")
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be positive")
    with SessionLocal() as db:
        rows = db.execute(
            select(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
        ).all()
        chunks = [row[0] for row in rows]
        for start in range(0, len(rows), args.batch_size):
            batch = rows[start:start + args.batch_size]
            vectors = embed_texts([chunk.chunk_text for chunk, _document in batch])
            for (chunk, document), vector in zip(batch, vectors, strict=True):
                chunk.embedding_json = json.dumps(vector)
                chunk.embedding_vector = vector if db.bind and db.bind.dialect.name == "postgresql" else json.dumps(vector)
                chunk.embedding_model = active_embedding_model()
                chunk.embedding_index_version = settings.embedding_index_version
                chunk.embedding_status = "indexed"
                chunk.content_type = classify_chunk_content(chunk.chunk_text)
                document.source_tier = source_tier(document.source_name, owner_user_id=document.owner_user_id)
                if document.document_type == "synthetic_demo_facts" or document.source_name == "Deterministic Demo Seed":
                    document.data_status = "synthetic_demo"
                elif document.owner_user_id:
                    document.data_status = "user_upload"
                else:
                    document.data_status = "observed"
                metadata = json.loads(chunk.metadata_json)
                metadata["embedding_backend"] = settings.embedding_backend
                metadata["embedding_model"] = active_embedding_model()
                metadata["embedding_index_version"] = settings.embedding_index_version
                metadata["content_type"] = chunk.content_type
                metadata["source_tier"] = document.source_tier
                metadata["data_status"] = document.data_status
                chunk.metadata_json = json.dumps(metadata)
                db.add(chunk)
                db.add(document)
            db.flush()
            print(f"Embedded {min(start + len(batch), len(rows))}/{len(rows)} chunks.", flush=True)
        db.commit()
    print(
        f"Reindexed {len(chunks)} RAG chunks with {active_embedding_model()} "
        f"(index version {settings.embedding_index_version})."
    )


if __name__ == "__main__":
    main()
