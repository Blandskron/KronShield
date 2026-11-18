"""Preserve a snapshot before attempting its database transaction."""

import json
from collections.abc import Callable
from hashlib import sha256
from uuid import uuid4

from application.report_input import SavedAudit
from infra.artifacts import publish_report


class ResultPersistenceFailure(Exception):
    def __init__(self, result_id: str, snapshot_path: str):
        super().__init__("Database persistence failed after publishing the JSON snapshot")
        self.result_id = result_id
        self.snapshot_path = snapshot_path


def save_result(audit: SavedAudit, persist: Callable[[dict, str], None]) -> tuple[str, str]:
    """JSON is the recovery copy if the database write fails."""
    snapshot = audit.model_dump(mode="json")
    result_id = str(audit.result_id or uuid4())
    snapshot["result_id"] = result_id
    content = json.dumps(snapshot, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
    if len(content.encode("utf-8")) > 1024 * 1024:
        raise ValueError("Expanded snapshot exceeds the recoverable input size")
    digest = sha256(content.encode("utf-8")).hexdigest()
    output = str(publish_report(content, "json"))
    try:
        persist(snapshot, digest)
    except Exception as error:
        raise ResultPersistenceFailure(result_id, output) from error
    return result_id, output
