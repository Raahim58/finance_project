from hashlib import sha256

from app.ingestion.artifact_store import LocalArtifactStore, S3ArtifactStore


class _Body:
    def __init__(self, content: bytes):
        self.content = content

    def read(self) -> bytes:
        return self.content


class FakeS3Client:
    class exceptions:
        class ClientError(Exception):
            def __init__(self, code: str):
                self.response = {"Error": {"Code": code}}

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def head_object(self, *, Bucket: str, Key: str):
        if (Bucket, Key) not in self.objects:
            raise self.exceptions.ClientError("404")
        content = self.objects[(Bucket, Key)]
        return {"ContentLength": len(content), "Metadata": {"sha256": sha256(content).hexdigest()}}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, Metadata: dict[str, str]):
        assert Metadata["sha256"] == sha256(Body).hexdigest()
        self.objects[(Bucket, Key)] = Body

    def get_object(self, *, Bucket: str, Key: str):
        return {"Body": _Body(self.objects[(Bucket, Key)])}


def test_local_store_round_trip(tmp_path):
    store = LocalArtifactStore(tmp_path)
    stored = store.put(b"artifact", ".json")
    assert store.exists(stored.storage_path)
    assert store.get(stored.storage_path) == b"artifact"
    assert stored.sha256 == sha256(b"artifact").hexdigest()


def test_s3_store_uses_content_addressed_keys_and_is_idempotent(monkeypatch):
    client = FakeS3Client()
    monkeypatch.setattr("app.ingestion.artifact_store.boto3.client", lambda *args, **kwargs: client)
    store = S3ArtifactStore(
        endpoint_url="http://minio:9000",
        region="us-east-1",
        bucket="psx-artifacts",
        access_key="test",
        secret_key="test",
    )
    first = store.put(b"artifact", ".pdf")
    second = store.put(b"artifact", ".html")
    digest = sha256(b"artifact").hexdigest()
    assert first.storage_path == f"s3://psx-artifacts/sha256/{digest[:2]}/{digest}"
    assert second.storage_path == first.storage_path
    assert store.get(first.storage_path) == b"artifact"
    assert store.exists(first.storage_path)
    assert len(client.objects) == 1
