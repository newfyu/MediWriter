from __future__ import annotations

import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .config import Settings
from .db import connect, initialize, row_to_dict
from .parser import parse_record_file


@dataclass
class IndexRunStats:
    started_at: str
    finished_at: str | None = None
    status: str = "running"
    total_files: int = 0
    scanned_files: int = 0
    indexed_files: int = 0
    skipped_files: int = 0
    error_files: int = 0
    message: str | None = None


class Indexer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        initialize(self.settings.index_db)

    def is_running(self) -> bool:
        return self._lock.locked()

    def latest_run(self) -> dict | None:
        with connect(self.settings.index_db) as conn:
            row = conn.execute(
                "SELECT * FROM index_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row_to_dict(row)

    def status(self) -> dict:
        with connect(self.settings.index_db) as conn:
            latest = conn.execute(
                "SELECT * FROM index_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_records,
                    SUM(CASE WHEN parse_status = 'ok' THEN 1 ELSE 0 END) AS parsed_records,
                    SUM(CASE WHEN parse_status != 'ok' THEN 1 ELSE 0 END) AS parse_errors,
                    MAX(parsed_at) AS last_indexed_at
                FROM records
                """
            ).fetchone()
        payload = row_to_dict(totals) or {}
        payload["is_running"] = self.is_running()
        payload["latest_run"] = row_to_dict(latest)
        payload["db_path"] = str(self.settings.index_db)
        payload["query_save_dir"] = str(self.settings.query_save_dir)
        payload["archive_dir"] = str(self.settings.archive_dir)
        payload["refresh_interval_seconds"] = self.settings.refresh_interval_seconds
        return payload

    def _iter_files(self) -> list[tuple[Path, str]]:
        pairs: list[tuple[Path, str]] = []
        for directory, source in (
            (self.settings.query_save_dir, "query_save"),
            (self.settings.archive_dir, "archive"),
        ):
            if not directory.exists():
                continue
            pairs.extend((path, source) for path in directory.glob("*.txt"))
        return pairs

    def scan_once(self) -> IndexRunStats:
        if not self._lock.acquire(blocking=False):
            latest = self.latest_run()
            return IndexRunStats(
                started_at=datetime.now().isoformat(timespec="seconds"),
                finished_at=datetime.now().isoformat(timespec="seconds"),
                status="skipped",
                message=f"index already running: {latest.get('started_at') if latest else 'unknown'}",
            )

        stats = IndexRunStats(started_at=datetime.now().isoformat(timespec="seconds"))
        run_id: int | None = None
        try:
            files = self._iter_files()
            stats.total_files = len(files)
            with connect(self.settings.index_db) as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO index_runs
                    (started_at, status, total_files, scanned_files, indexed_files, skipped_files, error_files)
                    VALUES (?, ?, ?, 0, 0, 0, 0)
                    """,
                    (stats.started_at, stats.status, stats.total_files),
                )
                run_id = cursor.lastrowid
                conn.commit()

                for path, source in files:
                    stats.scanned_files += 1
                    try:
                        stat = path.stat()
                    except OSError:
                        stats.error_files += 1
                        continue

                    existing = conn.execute(
                        "SELECT file_mtime, file_size FROM records WHERE path = ?",
                        (str(path.resolve()),),
                    ).fetchone()
                    if (
                        existing
                        and float(existing["file_mtime"]) == stat.st_mtime
                        and int(existing["file_size"]) == stat.st_size
                    ):
                        stats.skipped_files += 1
                        if stats.scanned_files % 500 == 0:
                            self._update_run(conn, run_id, stats)
                        continue

                    parsed = parse_record_file(path, source)
                    now = datetime.now().isoformat(timespec="seconds")
                    payload = asdict(parsed)
                    payload["path"] = str(path.resolve())
                    payload["file_mtime"] = stat.st_mtime
                    payload["file_size"] = stat.st_size
                    payload["parsed_at"] = now
                    self._upsert_record(conn, payload)
                    stats.indexed_files += 1
                    if parsed.parse_status != "ok":
                        stats.error_files += 1
                    if stats.scanned_files % 200 == 0:
                        self._update_run(conn, run_id, stats)

                stats.status = "success"
                stats.finished_at = datetime.now().isoformat(timespec="seconds")
                self._update_run(conn, run_id, stats)
                conn.commit()
            return stats
        except Exception as exc:
            stats.status = "error"
            stats.finished_at = datetime.now().isoformat(timespec="seconds")
            stats.message = str(exc)
            if run_id is not None:
                with connect(self.settings.index_db) as conn:
                    self._update_run(conn, run_id, stats)
                    conn.commit()
            return stats
        finally:
            self._lock.release()

    @staticmethod
    def _update_run(conn: sqlite3.Connection, run_id: int | None, stats: IndexRunStats) -> None:
        if run_id is None:
            return
        conn.execute(
            """
            UPDATE index_runs
            SET finished_at = ?, status = ?, total_files = ?, scanned_files = ?,
                indexed_files = ?, skipped_files = ?, error_files = ?, message = ?
            WHERE id = ?
            """,
            (
                stats.finished_at,
                stats.status,
                stats.total_files,
                stats.scanned_files,
                stats.indexed_files,
                stats.skipped_files,
                stats.error_files,
                stats.message,
                run_id,
            ),
        )
        conn.commit()

    @staticmethod
    def _upsert_record(conn: sqlite3.Connection, payload: dict) -> None:
        conn.execute(
            """
            INSERT INTO records (
                path, source, filename, file_mtime, file_size, parsed_at, parse_status,
                parse_error, doctor_id, doctor_name, department, patient_department,
                doc_type, command_info, record_time, record_date, record_hour,
                elapsed_seconds, input_chars, output_chars, total_chars
            ) VALUES (
                :path, :source, :filename, :file_mtime, :file_size, :parsed_at, :parse_status,
                :parse_error, :doctor_id, :doctor_name, :department, :patient_department,
                :doc_type, :command_info, :record_time, :record_date, :record_hour,
                :elapsed_seconds, :input_chars, :output_chars, :total_chars
            )
            ON CONFLICT(path) DO UPDATE SET
                source = excluded.source,
                filename = excluded.filename,
                file_mtime = excluded.file_mtime,
                file_size = excluded.file_size,
                parsed_at = excluded.parsed_at,
                parse_status = excluded.parse_status,
                parse_error = excluded.parse_error,
                doctor_id = excluded.doctor_id,
                doctor_name = excluded.doctor_name,
                department = excluded.department,
                patient_department = excluded.patient_department,
                doc_type = excluded.doc_type,
                command_info = excluded.command_info,
                record_time = excluded.record_time,
                record_date = excluded.record_date,
                record_hour = excluded.record_hour,
                elapsed_seconds = excluded.elapsed_seconds,
                input_chars = excluded.input_chars,
                output_chars = excluded.output_chars,
                total_chars = excluded.total_chars
            """,
            payload,
        )

