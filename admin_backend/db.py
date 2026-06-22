from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_mtime REAL NOT NULL,
    file_size INTEGER NOT NULL,
    parsed_at TEXT NOT NULL,
    parse_status TEXT NOT NULL,
    parse_error TEXT,
    doctor_id TEXT,
    doctor_name TEXT,
    department TEXT,
    patient_department TEXT,
    doc_type TEXT,
    command_info TEXT,
    record_time TEXT,
    record_date TEXT,
    record_hour INTEGER,
    elapsed_seconds REAL,
    input_chars INTEGER NOT NULL DEFAULT 0,
    output_chars INTEGER NOT NULL DEFAULT 0,
    total_chars INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_records_date ON records(record_date);
CREATE INDEX IF NOT EXISTS idx_records_source ON records(source);
CREATE INDEX IF NOT EXISTS idx_records_doctor ON records(doctor_id, doctor_name);
CREATE INDEX IF NOT EXISTS idx_records_department ON records(department);
CREATE INDEX IF NOT EXISTS idx_records_doc_type ON records(doc_type);
CREATE INDEX IF NOT EXISTS idx_records_status ON records(parse_status);

CREATE TABLE IF NOT EXISTS index_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    total_files INTEGER NOT NULL DEFAULT 0,
    scanned_files INTEGER NOT NULL DEFAULT 0,
    indexed_files INTEGER NOT NULL DEFAULT 0,
    skipped_files INTEGER NOT NULL DEFAULT 0,
    error_files INTEGER NOT NULL DEFAULT 0,
    message TEXT
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS template_test_inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    input_json TEXT NOT NULL,
    source_record_id INTEGER,
    source_filename TEXT,
    doc_type TEXT,
    doctor_name TEXT,
    department TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_run_at TEXT,
    FOREIGN KEY(source_record_id) REFERENCES records(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_template_test_inputs_updated
ON template_test_inputs(updated_at);

CREATE INDEX IF NOT EXISTS idx_template_test_inputs_doc_type
ON template_test_inputs(doc_type);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def initialize(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def rows_to_dicts(rows: Iterator[sqlite3.Row]) -> list[dict]:
    return [row_to_dict(row) for row in rows if row is not None]
