"""Normalize bounded legacy result files without altering the source."""

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from application.report_input import ReportFinding, SavedAudit


class FileFormat(str, Enum):
    JSON = "json"
    SQLITE = "sqlite"


MAX_FINDINGS = 1000
LIMITS = {FileFormat.JSON: 1024 * 1024, FileFormat.SQLITE: 16 * 1024 * 1024}


@dataclass(frozen=True)
class LegacyImport:
    source_format: FileFormat
    source_digest: str
    findings: list[dict]

    def summary(self) -> dict:
        return {"source_format": self.source_format.value, "source_digest": self.source_digest,
                "finding_count": len(self.findings), "origin": "legacy", "confidence": "unverified"}


def read_source(path: Path, source_format: FileFormat) -> bytes:
    wal = path.with_name(path.name + "-wal")
    journal = path.with_name(path.name + "-journal")

    def has_pending_journal():
        return source_format is FileFormat.SQLITE and any(
            sidecar.exists() and sidecar.stat().st_size for sidecar in (wal, journal)
        )

    if not path.is_file():
        raise ValueError("Expected a regular source file")
    if has_pending_journal():
        raise ValueError("Export a consistent SQLite backup without journal sidecars")
    with path.open("rb") as source:
        before = path.stat()
        raw = source.read(LIMITS[source_format] + 1)
        after = path.stat()
    if has_pending_journal() or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("Source changed while reading")
    return raw


def _finding(key: str, target_url: str, item: ReportFinding) -> dict:
    return {"record_key": key, "target_url": target_url, "observed_url": item.url, "type": item.type,
            "detail": item.detail, "reported_status": item.status.value if item.status else None,
            "reported_confidence": item.confidence.value if item.confidence else None,
            "origin": "legacy", "confidence": "unverified"}


def _snapshot(snapshot: SavedAudit, prefix: str) -> list[dict]:
    return [_finding(f"{prefix}/{index}", snapshot.url, item) for index, item in enumerate(snapshot.findings)]


def _sqlite(raw: bytes) -> list[dict]:
    if not raw.startswith(b"SQLite format 3\x00") or len(raw) < 100:
        raise ValueError("Invalid SQLite database")
    if raw[18:20] != b"\x01\x01":
        raise ValueError("Export a SQLite backup in rollback-journal format")
    with TemporaryDirectory() as tmp:
        file = Path(tmp) / "source.db"
        file.write_bytes(raw)
        with closing(sqlite3.connect(file.as_uri() + "?mode=ro&immutable=1", uri=True)) as database:
            deadline = monotonic() + 3
            database.set_progress_handler(lambda: int(monotonic() > deadline), 1000)
            database.execute("PRAGMA trusted_schema=OFF")
            database.execute("PRAGMA query_only=ON")
            tables = {row[0] for row in database.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND upper(sql) LIKE 'CREATE TABLE %' AND name IN ('findings','offline_results')"
            )}
            if not tables:
                raise ValueError("SQLite schema is not recognized")

            records = []
            if "findings" in tables:
                for row_id, target, kind, detail in database.execute(
                    "SELECT id, url, type, detail FROM findings ORDER BY id LIMIT ?", (MAX_FINDINGS + 1,)
                ):
                    if type(row_id) is not int:
                        raise ValueError("Invalid SQLite row identifier")
                    audit = SavedAudit(url=target, findings=(ReportFinding(type=kind, detail=detail),))
                    records.append(_finding(f"findings/{row_id}", audit.url, audit.findings[0]))
                    if len(records) > MAX_FINDINGS:
                        raise ValueError("Source exceeds 1000 findings")
            if "offline_results" in tables:
                rows = database.execute("""
                    SELECT id, snapshot FROM offline_results ORDER BY id LIMIT ?
                """, (MAX_FINDINGS + 1,))
                for index, (result_id, encoded) in enumerate(rows):
                    if index >= MAX_FINDINGS or not isinstance(encoded, str) or len(encoded) > LIMITS[FileFormat.JSON]:
                        raise ValueError("Invalid or oversized SQLite snapshot")
                    snapshot = SavedAudit.model_validate_json(encoded)
                    if snapshot.result_id is None or str(snapshot.result_id) != result_id:
                        raise ValueError("Invalid SQLite result identifier")
                    records.extend(_snapshot(snapshot, f"offline_results/{result_id}"))
                    if len(records) > MAX_FINDINGS:
                        raise ValueError("Source exceeds 1000 findings")
            return records


def parse_source(raw: bytes, source_format: FileFormat) -> LegacyImport:
    if len(raw) > LIMITS[source_format]:
        raise ValueError("Source exceeds the format size limit")
    try:
        if source_format is FileFormat.JSON:
            snapshot = SavedAudit.model_validate_json(raw)
            records = _snapshot(snapshot, f"json/{snapshot.result_id or 'root'}")
        else:
            records = _sqlite(raw)
        # PostgreSQL JSONB cannot represent an embedded null character.
        if any("\x00" in value for record in records for value in record.values() if isinstance(value, str)):
            raise ValueError("Source contains an invalid null character")
        if len(json.dumps(records, ensure_ascii=False).encode("utf-8")) > 8 * 1024 * 1024:
            raise ValueError("Normalized source exceeds 8 MiB")
    except (sqlite3.Error, UnicodeError, TypeError, ValueError):
        raise ValueError("Invalid or oversized legacy source") from None
    return LegacyImport(source_format, sha256(raw).hexdigest(), records)
