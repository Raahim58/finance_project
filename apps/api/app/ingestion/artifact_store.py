from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class StoredArtifact:
    sha256: str
    storage_path: str
    bytes: int


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
