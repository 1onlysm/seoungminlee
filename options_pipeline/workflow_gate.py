"""Fail-closed output gates used by the offline workflow and future collector."""
from pathlib import Path

from .storage import StorageError, validate_collection_output


def validate_required_output(snapshot_dir, require_live=False):
    path = Path(snapshot_dir)
    if not path.exists():
        raise StorageError("MISSING_ARTIFACT_OR_SNAPSHOT")
    result = validate_collection_output(path, require_production_evidence=require_live)
    if not result["record_count"]:
        raise StorageError("EMPTY_OUTPUT_CANNOT_BE_SUCCESS")
    return result

