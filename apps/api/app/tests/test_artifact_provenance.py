from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.workstation import SourceArtifact
from app.services.ingestion_persistence import source, store_artifact


def test_identical_bytes_keep_source_and_request_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "source_artifact_root", str(tmp_path / "artifacts"))
    with SessionLocal() as db:
        first_source = source(db, "Fixture A", "news", "https://a.test", 10, 60, "fixture")
        second_source = source(db, "Fixture B", "news", "https://b.test", 20, 60, "fixture")
        first = store_artifact(db, first_source, b"same bytes", url="https://a.test/one", method="GET", parser_version="fixture", content_type="text/plain")
        same_request = store_artifact(db, first_source, b"same bytes", url="https://a.test/one", method="GET", parser_version="fixture", content_type="text/plain")
        different_url = store_artifact(db, first_source, b"same bytes", url="https://a.test/two", method="GET", parser_version="fixture", content_type="text/plain")
        different_source = store_artifact(db, second_source, b"same bytes", url="https://b.test/one", method="GET", parser_version="fixture", content_type="text/plain")
        db.commit()

        count = db.scalar(select(func.count()).select_from(SourceArtifact))
        ids = (first.id, same_request.id, different_url.id, different_source.id)

    assert ids[1] == ids[0]
    assert ids[2] != ids[0]
    assert ids[3] != ids[0]
    assert count == 3
