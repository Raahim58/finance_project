from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol

import boto3
from botocore.config import Config

from app.core.config import Settings, settings


@dataclass(frozen=True)
class StoredArtifact:
    sha256: str
    storage_path: str
    bytes: int


class ArtifactStore(Protocol):
    def put(self, content: bytes, suffix: str = ".bin") -> StoredArtifact: ...

    def get(self, storage_path: str) -> bytes: ...

    def exists(self, storage_path: str) -> bool: ...

    def check(self) -> None: ...


class LocalArtifactStore:
    """Content-addressed immutable raw storage; paths are never derived from source input."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def put(self, content: bytes, suffix: str = ".bin") -> StoredArtifact:
        digest = sha256(content).hexdigest()
        day = datetime.now(UTC).strftime("%Y/%m/%d")
        directory = self.root / day
        directory.mkdir(parents=True, exist_ok=True)
        safe_suffix = suffix if suffix in {".json", ".html", ".csv", ".zip", ".bin"} else ".bin"
        target = directory / f"{digest}{safe_suffix}"
        if not target.exists():
            target.write_bytes(content)
        return StoredArtifact(digest, str(target), len(content))

    def get(self, storage_path: str) -> bytes:
        return Path(storage_path).read_bytes()

    def exists(self, storage_path: str) -> bool:
        return Path(storage_path).is_file()

    def check(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)


class S3ArtifactStore:
    """Private S3-compatible, content-addressed artifact storage."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        region: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        addressing_style: str = "path",
    ) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(s3={"addressing_style": addressing_style}),
        )

    @staticmethod
    def key_for_digest(digest: str) -> str:
        return f"sha256/{digest[:2]}/{digest}"

    def _key(self, storage_path: str) -> str:
        prefix = f"s3://{self.bucket}/"
        if not storage_path.startswith(prefix):
            raise ValueError(f"Artifact URI is not in bucket {self.bucket!r}")
        return storage_path[len(prefix):]

    def put(self, content: bytes, suffix: str = ".bin") -> StoredArtifact:
        del suffix  # Object identity is the content hash, not a source filename.
        digest = sha256(content).hexdigest()
        key = self.key_for_digest(digest)
        uri = f"s3://{self.bucket}/{key}"
        try:
            existing = self.client.head_object(Bucket=self.bucket, Key=key)
            recorded_digest = existing.get("Metadata", {}).get("sha256")
            if existing.get("ContentLength") != len(content) or recorded_digest not in {None, digest}:
                raise RuntimeError(f"Existing artifact object failed metadata validation: {uri}")
        except self.client.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
                raise
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                Metadata={"sha256": digest},
            )
        return StoredArtifact(digest, uri, len(content))

    def get(self, storage_path: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=self._key(storage_path))
        return response["Body"].read()

    def exists(self, storage_path: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(storage_path))
            return True
        except self.client.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def check(self) -> None:
        self.client.head_bucket(Bucket=self.bucket)


def get_artifact_store(config: Settings = settings) -> ArtifactStore:
    if config.artifact_storage_backend == "local":
        return LocalArtifactStore(config.source_artifact_root)
    return S3ArtifactStore(
        endpoint_url=config.artifact_s3_endpoint_url,
        region=config.artifact_s3_region,
        bucket=config.artifact_s3_bucket,
        access_key=config.artifact_s3_access_key,
        secret_key=config.artifact_s3_secret_key,
        addressing_style=config.artifact_s3_addressing_style,
    )
