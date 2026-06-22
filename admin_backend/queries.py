from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts


@dataclass
class RecordFilters:
    date_from: str | None = None
    date_to: str | None = None
    doctor_id: str | None = None
    department: str | None = None
    doc_type: str | None = None
    source: str | None = None
    status: str | None = None
    q: str | None = None


def _where(filters: RecordFilters) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if filters.date_from:
        clauses.append("record_date >= :date_from")
        params["date_from"] = filters.date_from
    if filters.date_to:
        clauses.append("record_date <= :date_to")
        params["date_to"] = filters.date_to
    if filters.doctor_id:
        clauses.append("doctor_id = :doctor_id")
        params["doctor_id"] = filters.doctor_id
    if filters.department:
        clauses.append("department = :department")
        params["department"] = filters.department
    if filters.doc_type:
        clauses.append("doc_type = :doc_type")
        params["doc_type"] = filters.doc_type
    if filters.source:
        clauses.append("source = :source")
        params["source"] = filters.source
    if filters.status:
        clauses.append("parse_status = :status")
        params["status"] = filters.status
    if filters.q:
        clauses.append(
            """
            (
                filename LIKE :q OR doctor_name LIKE :q OR doctor_id LIKE :q OR
                department LIKE :q OR doc_type LIKE :q OR command_info LIKE :q
            )
            """
        )
        params["q"] = f"%{filters.q}%"
    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(clauses), params


def _where_without_dates(filters: RecordFilters) -> tuple[str, dict[str, Any]]:
    return _where(
        RecordFilters(
            doctor_id=filters.doctor_id,
            department=filters.department,
            doc_type=filters.doc_type,
            source=filters.source,
            status=filters.status,
            q=filters.q,
        )
    )


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def dashboard_summary(db_path: Path, filters: RecordFilters) -> dict:
    where, params = _where(filters)
    with connect(db_path) as conn:
        summary = conn.execute(
            f"""
            SELECT
                COUNT(*) AS total_records,
                SUM(CASE WHEN parse_status = 'ok' THEN 1 ELSE 0 END) AS parsed_records,
                SUM(CASE WHEN parse_status != 'ok' THEN 1 ELSE 0 END) AS parse_errors,
                COUNT(DISTINCT CASE WHEN parse_status = 'ok' THEN doctor_id END) AS active_doctors,
                COUNT(DISTINCT CASE WHEN parse_status = 'ok' THEN doc_type END) AS doc_types,
                AVG(CASE WHEN parse_status = 'ok' THEN elapsed_seconds END) AS avg_elapsed_seconds,
                MAX(parsed_at) AS last_indexed_at,
                MIN(record_date) AS first_record_date,
                MAX(record_date) AS last_record_date
            FROM records
            {where}
            """,
            params,
        ).fetchone()
        elapsed_rows = conn.execute(
            f"""
            SELECT elapsed_seconds FROM records
            {where}
            {'AND' if where else 'WHERE'} parse_status = 'ok' AND elapsed_seconds IS NOT NULL
            """,
            params,
        ).fetchall()
        today = conn.execute(
            f"""
            SELECT COUNT(*) AS count FROM records
            {where}
            {'AND' if where else 'WHERE'} parse_status = 'ok'
            AND record_date = date('now', 'localtime')
            """,
            params,
        ).fetchone()
        last_7 = conn.execute(
            f"""
            SELECT COUNT(*) AS count FROM records
            {where}
            {'AND' if where else 'WHERE'} parse_status = 'ok'
            AND record_date >= date('now', 'localtime', '-6 day')
            """,
            params,
        ).fetchone()
        last_30 = conn.execute(
            f"""
            SELECT COUNT(*) AS count FROM records
            {where}
            {'AND' if where else 'WHERE'} parse_status = 'ok'
            AND record_date >= date('now', 'localtime', '-29 day')
            """,
            params,
        ).fetchone()

    elapsed = [float(row["elapsed_seconds"]) for row in elapsed_rows]
    payload = row_to_dict(summary) or {}
    payload["today_records"] = int(today["count"] or 0)
    payload["last_7_days_records"] = int(last_7["count"] or 0)
    payload["last_30_days_records"] = int(last_30["count"] or 0)
    payload["p50_elapsed_seconds"] = _percentile(elapsed, 0.5)
    payload["p95_elapsed_seconds"] = _percentile(elapsed, 0.95)
    return payload


def dashboard_trends(db_path: Path, filters: RecordFilters) -> dict:
    where, params = _where(filters)
    hour_where, hour_params = _where_without_dates(filters)
    with connect(db_path) as conn:
        daily = rows_to_dicts(
            conn.execute(
                f"""
                SELECT record_date AS date, COUNT(*) AS count
                FROM records
                {where}
                {'AND' if where else 'WHERE'} parse_status = 'ok' AND record_date IS NOT NULL
                GROUP BY record_date
                ORDER BY record_date
                """,
                params,
            )
        )
        hourly = rows_to_dicts(
            conn.execute(
                f"""
                SELECT record_hour AS hour, COUNT(*) AS count
                FROM records
                {where}
                {'AND' if where else 'WHERE'} parse_status = 'ok' AND record_hour IS NOT NULL
                GROUP BY record_hour
                ORDER BY record_hour
                """,
                params,
            )
        )
        hourly_today = rows_to_dicts(
            conn.execute(
                f"""
                SELECT record_hour AS hour, COUNT(*) AS count
                FROM records
                {hour_where}
                {'AND' if hour_where else 'WHERE'} parse_status = 'ok'
                AND record_hour IS NOT NULL
                AND record_date = date('now', 'localtime')
                GROUP BY record_hour
                ORDER BY record_hour
                """,
                hour_params,
            )
        )
        hourly_7day_avg = rows_to_dicts(
            conn.execute(
                f"""
                SELECT record_hour AS hour, COUNT(*) / 7.0 AS count
                FROM records
                {hour_where}
                {'AND' if hour_where else 'WHERE'} parse_status = 'ok'
                AND record_hour IS NOT NULL
                AND record_date >= date('now', 'localtime', '-6 day')
                GROUP BY record_hour
                ORDER BY record_hour
                """,
                hour_params,
            )
        )
        sources = rows_to_dicts(
            conn.execute(
                f"""
                SELECT source, COUNT(*) AS count
                FROM records
                {where}
                GROUP BY source
                ORDER BY count DESC
                """,
                params,
            )
        )
    return {
        "daily": daily,
        "hourly": hourly,
        "hourly_today": hourly_today,
        "hourly_7day_avg": hourly_7day_avg,
        "sources": sources,
    }


def dashboard_breakdowns(db_path: Path, filters: RecordFilters) -> dict:
    where, params = _where(filters)
    with connect(db_path) as conn:
        doctors = rows_to_dicts(
            conn.execute(
                f"""
                SELECT doctor_id, COALESCE(doctor_name, doctor_id, '未知') AS doctor_name,
                       COUNT(*) AS count, AVG(elapsed_seconds) AS avg_elapsed_seconds
                FROM records
                {where}
                {'AND' if where else 'WHERE'} parse_status = 'ok'
                GROUP BY doctor_id, doctor_name
                ORDER BY count DESC
                LIMIT 20
                """,
                params,
            )
        )
        departments = rows_to_dicts(
            conn.execute(
                f"""
                SELECT COALESCE(department, '未知科室') AS department,
                       COUNT(*) AS count
                FROM records
                {where}
                {'AND' if where else 'WHERE'} parse_status = 'ok'
                GROUP BY department
                ORDER BY count DESC
                LIMIT 20
                """,
                params,
            )
        )
        doc_types = rows_to_dicts(
            conn.execute(
                f"""
                SELECT COALESCE(doc_type, '未知类型') AS doc_type,
                       COUNT(*) AS count, AVG(elapsed_seconds) AS avg_elapsed_seconds
                FROM records
                {where}
                {'AND' if where else 'WHERE'} parse_status = 'ok'
                GROUP BY doc_type
                ORDER BY count DESC
                LIMIT 30
                """,
                params,
            )
        )
        sources = rows_to_dicts(
            conn.execute(
                f"""
                SELECT source, COUNT(*) AS count
                FROM records
                {where}
                GROUP BY source
                ORDER BY count DESC
                """,
                params,
            )
        )
        statuses = rows_to_dicts(
            conn.execute(
                f"""
                SELECT parse_status AS status, COUNT(*) AS count
                FROM records
                {where}
                GROUP BY parse_status
                ORDER BY count DESC
                """,
                params,
            )
        )
    return {
        "doctors": doctors,
        "departments": departments,
        "doc_types": doc_types,
        "sources": sources,
        "statuses": statuses,
    }


def command_info_analysis(
    db_path: Path,
    filters: RecordFilters,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 50)
    offset = (page - 1) * page_size
    where, params = _where(filters)
    command_clause = "command_info IS NOT NULL AND TRIM(command_info) != ''"
    command_prefix = f"{where} {'AND' if where else 'WHERE'} {command_clause}"
    with connect(db_path) as conn:
        summary = row_to_dict(
            conn.execute(
                f"""
                SELECT
                    COUNT(*) AS total_records,
                    SUM(CASE WHEN {command_clause} THEN 1 ELSE 0 END) AS command_records,
                    AVG(CASE WHEN {command_clause} THEN LENGTH(command_info) END) AS avg_command_length,
                    MAX(CASE WHEN {command_clause} THEN record_time END) AS latest_command_time
                FROM records
                {where}
                """,
                params,
            ).fetchone()
        ) or {}
        today = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM records
            {command_prefix}
            AND record_date = date('now', 'localtime')
            """,
            params,
        ).fetchone()
        last_7 = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM records
            {command_prefix}
            AND record_date >= date('now', 'localtime', '-6 day')
            """,
            params,
        ).fetchone()
        daily = rows_to_dicts(
            conn.execute(
                f"""
                SELECT record_date AS date, COUNT(*) AS count
                FROM records
                {command_prefix}
                AND record_date IS NOT NULL
                GROUP BY record_date
                ORDER BY record_date
                """,
                params,
            )
        )
        doctors = rows_to_dicts(
            conn.execute(
                f"""
                SELECT doctor_id, COALESCE(doctor_name, doctor_id, '未知') AS doctor_name,
                       COUNT(*) AS count
                FROM records
                {command_prefix}
                GROUP BY doctor_id, doctor_name
                ORDER BY count DESC
                LIMIT 20
                """,
                params,
            )
        )
        departments = rows_to_dicts(
            conn.execute(
                f"""
                SELECT COALESCE(department, '未知科室') AS department,
                       COUNT(*) AS count
                FROM records
                {command_prefix}
                GROUP BY department
                ORDER BY count DESC
                LIMIT 20
                """,
                params,
            )
        )
        doc_types = rows_to_dicts(
            conn.execute(
                f"""
                SELECT COALESCE(doc_type, '未知类型') AS doc_type,
                       COUNT(*) AS count
                FROM records
                {command_prefix}
                GROUP BY doc_type
                ORDER BY count DESC
                LIMIT 20
                """,
                params,
            )
        )
        length_buckets = rows_to_dicts(
            conn.execute(
                f"""
                SELECT bucket, COUNT(*) AS count
                FROM (
                    SELECT
                        CASE
                            WHEN LENGTH(command_info) < 20 THEN '<20'
                            WHEN LENGTH(command_info) < 50 THEN '20-49'
                            WHEN LENGTH(command_info) < 100 THEN '50-99'
                            WHEN LENGTH(command_info) < 200 THEN '100-199'
                            ELSE '200+'
                        END AS bucket
                    FROM records
                    {command_prefix}
                )
                GROUP BY bucket
                ORDER BY
                    CASE bucket
                        WHEN '<20' THEN 1
                        WHEN '20-49' THEN 2
                        WHEN '50-99' THEN 3
                        WHEN '100-199' THEN 4
                        ELSE 5
                    END
                """,
                params,
            )
        )
        recent_total = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM records
            {command_prefix}
            """,
            params,
        ).fetchone()["count"]
        recent = rows_to_dicts(
            conn.execute(
                f"""
                SELECT id, source, filename, doctor_id, doctor_name, department,
                       doc_type, command_info, record_time, elapsed_seconds
                FROM records
                {command_prefix}
                ORDER BY COALESCE(record_time, parsed_at) DESC, id DESC
                LIMIT :limit OFFSET :offset
                """,
                {**params, "limit": page_size, "offset": offset},
            )
        )

    total = int(summary.get("total_records") or 0)
    command_count = int(summary.get("command_records") or 0)
    summary["command_records"] = command_count
    summary["today_command_records"] = int(today["count"] or 0)
    summary["last_7_days_command_records"] = int(last_7["count"] or 0)
    summary["command_coverage"] = command_count / total if total else 0
    return {
        "summary": summary,
        "daily": daily,
        "doctors": doctors,
        "departments": departments,
        "doc_types": doc_types,
        "length_buckets": length_buckets,
        "recent": recent,
        "recent_total": recent_total,
        "recent_page": page,
        "recent_page_size": page_size,
    }


def list_records(db_path: Path, filters: RecordFilters, page: int, page_size: int) -> dict:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    offset = (page - 1) * page_size
    where, params = _where(filters)
    with connect(db_path) as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS count FROM records {where}", params
        ).fetchone()["count"]
        rows = rows_to_dicts(
            conn.execute(
                f"""
                SELECT id, source, filename, parse_status, parse_error, doctor_id,
                       doctor_name, department, patient_department, doc_type,
                       command_info, record_time, record_date, record_hour,
                       elapsed_seconds, input_chars, output_chars, total_chars,
                       parsed_at
                FROM records
                {where}
                ORDER BY COALESCE(record_time, parsed_at) DESC, id DESC
                LIMIT :limit OFFSET :offset
                """,
                {**params, "limit": page_size, "offset": offset},
            )
        )
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def get_record(db_path: Path, record_id: int) -> dict | None:
    with connect(db_path) as conn:
        return row_to_dict(
            conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        )


def normalize_input_json(input_json: str) -> tuple[dict[str, Any], str]:
    try:
        value = json.loads(input_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"input JSON 格式错误: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("input 必须是 JSON object")
    return value, json.dumps(value, ensure_ascii=False, indent=2)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def list_template_test_inputs(db_path: Path, q: str | None = None) -> list[dict]:
    where = ""
    params: dict[str, Any] = {}
    if q:
        where = """
        WHERE title LIKE :q OR source_filename LIKE :q OR doc_type LIKE :q
              OR doctor_name LIKE :q OR department LIKE :q
        """
        params["q"] = f"%{q}%"
    with connect(db_path) as conn:
        return rows_to_dicts(
            conn.execute(
                f"""
                SELECT id, title, input_json, source_record_id, source_filename,
                       doc_type, doctor_name, department, created_at, updated_at,
                       last_run_at
                FROM template_test_inputs
                {where}
                ORDER BY updated_at DESC, id DESC
                """,
                params,
            )
        )


def get_template_test_input(db_path: Path, input_id: int) -> dict | None:
    with connect(db_path) as conn:
        return row_to_dict(
            conn.execute(
                """
                SELECT id, title, input_json, source_record_id, source_filename,
                       doc_type, doctor_name, department, created_at, updated_at,
                       last_run_at
                FROM template_test_inputs
                WHERE id = ?
                """,
                (input_id,),
            ).fetchone()
        )


def create_template_test_input(
    db_path: Path,
    *,
    title: str,
    input_json: str,
    source_record_id: int | None = None,
    source_filename: str | None = None,
    doc_type: str | None = None,
    doctor_name: str | None = None,
    department: str | None = None,
) -> dict:
    parsed, normalized = normalize_input_json(input_json)
    title = title.strip() or str(parsed.get("DocType") or "未命名测试 input")
    now = _now()
    with connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO template_test_inputs (
                title, input_json, source_record_id, source_filename, doc_type,
                doctor_name, department, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                normalized,
                source_record_id,
                source_filename,
                doc_type or parsed.get("DocType"),
                doctor_name,
                department,
                now,
                now,
            ),
        )
        conn.commit()
        return get_template_test_input(db_path, int(cursor.lastrowid)) or {}


def update_template_test_input(
    db_path: Path,
    input_id: int,
    *,
    title: str | None = None,
    input_json: str | None = None,
) -> dict | None:
    current = get_template_test_input(db_path, input_id)
    if not current:
        return None

    next_title = current["title"] if title is None else title.strip()
    if not next_title:
        raise ValueError("标题不能为空")

    normalized = current["input_json"]
    doc_type = current["doc_type"]
    if input_json is not None:
        parsed, normalized = normalize_input_json(input_json)
        doc_type = parsed.get("DocType") or doc_type

    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE template_test_inputs
            SET title = ?, input_json = ?, doc_type = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_title, normalized, doc_type, _now(), input_id),
        )
        conn.commit()
    return get_template_test_input(db_path, input_id)


def delete_template_test_input(db_path: Path, input_id: int) -> bool:
    with connect(db_path) as conn:
        cursor = conn.execute("DELETE FROM template_test_inputs WHERE id = ?", (input_id,))
        conn.commit()
        return cursor.rowcount > 0


def mark_template_test_input_run(db_path: Path, input_id: int) -> dict | None:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE template_test_inputs SET last_run_at = ?, updated_at = ? WHERE id = ?",
            (_now(), _now(), input_id),
        )
        conn.commit()
    return get_template_test_input(db_path, input_id)
