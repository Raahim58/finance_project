"""Move legacy filesystem artifacts into the configured S3-compatible store.

The command is deliberately resumable: database paths are changed only after
the source hash and uploaded object hash both match the recorded SHA-256.
"""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.artifact_store import S3ArtifactStore, get_artifact_store
from app.models.workstation import SourceArtifact


def _path_maps(values: list[str]) -> list[tuple[Path, Path]]:
    mappings: list[tuple[Path, Path]] = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"Invalid --path-map {value!r}; expected OLD=NEW")
        old, new = value.split("=", 1)
        mappings.append((Path(old), Path(new)))
    return mappings


def _resolve(path: str, mappings: list[tuple[Path, Path]]) -> Path:
    candidate = Path(path)
    if candidate.is_file():
        return candidate
    for old, new in mappings:
        try:
            relative = candidate.relative_to(old)
        except ValueError:
            continue
        mapped = new / relative
        if mapped.is_file():
            return mapped
    raise FileNotFoundError(path)


def migrate(
    *,
    apply: bool,
    verify: bool,
    mappings: list[tuple[Path, Path]],
    scan_roots: list[Path] | None = None,
) -> dict[str, object]:
    store = get_artifact_store(settings)
    if not isinstance(store, S3ArtifactStore):
        raise RuntimeError("Set ARTIFACT_STORAGE_BACKEND=s3 before running artifact migration")

    summary: dict[str, object] = {
        "mode": "apply" if apply else "verify" if verify else "dry-run",
        "examined": 0,
        "uploaded": 0,
        "already_remote": 0,
        "missing": [],
        "hash_mismatch": [],
        "scanned_files": 0,
        "unreferenced_files": 0,
        "unreferenced_missing": [],
    }
    with SessionLocal() as db:
        artifacts = db.scalars(
            select(SourceArtifact)
            .where(SourceArtifact.storage_path.is_not(None))
            .order_by(SourceArtifact.id)
        ).all()
        for artifact in artifacts:
            summary["examined"] = int(summary["examined"]) + 1
            storage_path = artifact.storage_path or ""
            if storage_path.startswith("s3://"):
                if not store.exists(storage_path):
                    cast_list = summary["missing"]
                    assert isinstance(cast_list, list)
                    cast_list.append({"id": artifact.id, "path": storage_path})
                    continue
                if verify and sha256(store.get(storage_path)).hexdigest() != artifact.sha256:
                    cast_list = summary["hash_mismatch"]
                    assert isinstance(cast_list, list)
                    cast_list.append({"id": artifact.id, "path": storage_path})
                    continue
                summary["already_remote"] = int(summary["already_remote"]) + 1
                continue

            try:
                source = _resolve(storage_path, mappings)
            except FileNotFoundError:
                cast_list = summary["missing"]
                assert isinstance(cast_list, list)
                cast_list.append({"id": artifact.id, "path": storage_path})
                continue
            content = source.read_bytes()
            digest = sha256(content).hexdigest()
            if digest != artifact.sha256:
                cast_list = summary["hash_mismatch"]
                assert isinstance(cast_list, list)
                cast_list.append({"id": artifact.id, "path": storage_path, "actual": digest})
                continue
            if not apply:
                continue
            stored = store.put(content)
            if stored.sha256 != artifact.sha256 or sha256(store.get(stored.storage_path)).hexdigest() != artifact.sha256:
                raise RuntimeError(f"Uploaded verification failed for artifact {artifact.id}")
            artifact.storage_path = stored.storage_path
            db.commit()
            summary["uploaded"] = int(summary["uploaded"]) + 1
    # Preserve files that have no database row without manufacturing provenance.
    for root in scan_roots or []:
        for source in root.rglob("*"):
            if not source.is_file():
                continue
            summary["scanned_files"] = int(summary["scanned_files"]) + 1
            content = source.read_bytes()
            digest = sha256(content).hexdigest()
            uri = f"s3://{store.bucket}/{store.key_for_digest(digest)}"
            if not store.exists(uri):
                summary["unreferenced_files"] = int(summary["unreferenced_files"]) + 1
                if apply:
                    stored = store.put(content)
                    if sha256(store.get(stored.storage_path)).hexdigest() != digest:
                        raise RuntimeError(f"Uploaded verification failed for unreferenced file {source}")
                elif verify:
                    cast_list = summary["unreferenced_missing"]
                    assert isinstance(cast_list, list)
                    cast_list.append({"path": str(source), "sha256": digest})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Upload, verify, then update each database row")
    mode.add_argument("--verify", action="store_true", help="Verify already migrated S3 objects")
    parser.add_argument(
        "--path-map",
        action="append",
        default=[],
        metavar="OLD=NEW",
        help="Resolve a legacy path prefix at a new mounted location; repeat as needed",
    )
    parser.add_argument("--manifest", type=Path, help="Write a JSON result manifest")
    parser.add_argument(
        "--scan-root",
        action="append",
        default=[],
        type=Path,
        help="Also preserve every file under this root, without creating database rows",
    )
    args = parser.parse_args()
    summary = migrate(
        apply=args.apply,
        verify=args.verify,
        mappings=_path_maps(args.path_map),
        scan_roots=args.scan_root,
    )
    payload = json.dumps(summary, indent=2, sort_keys=True)
    print(payload)
    if args.manifest:
        args.manifest.write_text(payload + "\n", encoding="utf-8")
    if summary["missing"] or summary["hash_mismatch"] or summary["unreferenced_missing"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
