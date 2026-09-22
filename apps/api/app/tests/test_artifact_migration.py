from pathlib import Path

import pytest

from app.jobs.migrate_artifacts import _path_maps, _resolve


def test_legacy_path_mapping_resolves_preserved_layout(tmp_path):
    imported = tmp_path / "imported"
    target = imported / "2026" / "09" / "artifact.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"artifact")

    mappings = _path_maps([f"/legacy/artifacts={imported}"])

    assert _resolve("/legacy/artifacts/2026/09/artifact.bin", mappings) == target


def test_legacy_path_mapping_rejects_invalid_argument():
    with pytest.raises(ValueError, match="expected OLD=NEW"):
        _path_maps(["missing-separator"])


def test_resolve_does_not_guess_missing_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        _resolve("/legacy/artifacts/missing.bin", [(Path("/legacy/artifacts"), tmp_path)])
