from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from blood_glucose_mcp import _clean_text, _log, _read_int_env
from env_config import load_mediwriter_env


MEDICHECK_SUGGESTIONS_KEY = "MediCheck补充文书建议"
MEDICHECK_SUGGESTION_NOTICE = "这是外部质控建议，需根据实际情况选择是否在当前病历中关注"
DEFAULT_MAX_SUGGESTIONS = 8
RECENT_REVIEW_WINDOW = timedelta(days=3)


def enrich_query_with_medicheck_suggestions(query_json: dict[str, Any], logger: Any | None = None) -> dict[str, Any]:
    existing = query_json.get(MEDICHECK_SUGGESTIONS_KEY)
    if isinstance(existing, list) and existing:
        return query_json

    query_json[MEDICHECK_SUGGESTIONS_KEY] = []
    if not _enabled():
        return query_json

    patient_no = _extract_patient_no(query_json)
    if not patient_no:
        _log(logger, "warning", "缺少 PatInfo.PatientNo，跳过 MediCheck 质控补充建议")
        return query_json

    doc_type = _clean_text(query_json.get("DocType"))
    if not doc_type:
        _log(logger, "warning", "缺少 DocType，跳过 MediCheck 质控补充建议")
        return query_json

    try:
        query_json[MEDICHECK_SUGGESTIONS_KEY] = fetch_medicheck_suggestions(patient_no, doc_type)
    except Exception as exc:
        query_json[MEDICHECK_SUGGESTIONS_KEY] = []
        _log(logger, "warning", f"MediCheck 质控补充建议查询失败，已留空: {exc}")
    return query_json


def fetch_medicheck_suggestions(patient_no: str, doc_type: str) -> list[dict[str, str]]:
    load_mediwriter_env()
    database_url = _database_url()
    if not database_url:
        raise RuntimeError("missing MEDIWRITER_MEDICHECK_DATABASE_URL or MEDICHECK_DATABASE_URL")

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("psycopg is required for MediCheck suggestions") from exc

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        latest_run = conn.execute(
            """
            SELECT run_id, checked_at
            FROM review_runs
            WHERE patient_no = %s
            ORDER BY checked_at DESC, run_seq DESC
            LIMIT 1
            """,
            (patient_no,),
        ).fetchone()
        if latest_run is None:
            return []
        findings = conn.execute(
            """
            SELECT checklist_id, severity, title, description, recommendation, status, created_at
            FROM findings
            WHERE run_id = %s AND status = 'accepted'
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2
                    WHEN 'low' THEN 3
                    ELSE 4
                END,
                created_at DESC
            """,
            (latest_run["run_id"],),
        ).fetchall()

    return build_medicheck_suggestions(
        latest_run=dict(latest_run),
        finding_rows=[dict(row) for row in findings],
        rules=load_medicheck_rules(),
        doc_type=doc_type,
        max_suggestions=_read_int_env("MEDIWRITER_MEDICHECK_MAX_SUGGESTIONS", DEFAULT_MAX_SUGGESTIONS),
    )


def build_medicheck_suggestions(
    *,
    latest_run: dict[str, Any] | None,
    finding_rows: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    doc_type: str,
    now: datetime | None = None,
    max_suggestions: int = DEFAULT_MAX_SUGGESTIONS,
) -> list[dict[str, str]]:
    if not latest_run:
        return []
    checked_at_value = latest_run.get("checked_at")
    checked_at = _parse_datetime(checked_at_value)
    if checked_at is None:
        return []
    checked_at_text = _format_datetime(checked_at_value, checked_at)
    current_time = now or datetime.now(checked_at.tzinfo)
    if checked_at.tzinfo is not None and current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=checked_at.tzinfo)
    elif checked_at.tzinfo is None and current_time.tzinfo is not None:
        checked_at = checked_at.replace(tzinfo=current_time.tzinfo)
    if checked_at < current_time - RECENT_REVIEW_WINDOW:
        return []

    rules_by_id = {
        _clean_text(rule.get("id")): rule
        for rule in rules
        if isinstance(rule, dict) and _clean_text(rule.get("id"))
    }
    current_doc_type = _clean_text(doc_type)
    suggestions: list[dict[str, str]] = []
    limit = max(1, int(max_suggestions or DEFAULT_MAX_SUGGESTIONS))
    for row in finding_rows:
        if _clean_text(row.get("status")) != "accepted":
            continue
        checklist_id = _clean_text(row.get("checklist_id"))
        rule = rules_by_id.get(checklist_id)
        if not rule:
            continue
        keywords = _clean_text_list(rule.get("mediwriter_supplement_keywords"))
        if not keywords or not any(keyword in current_doc_type for keyword in keywords):
            continue
        suggestions.append(
            {
                "提示": MEDICHECK_SUGGESTION_NOTICE,
                "质控时间": checked_at_text,
                "规则": _clean_text(rule.get("title")) or checklist_id,
                "规则编号": checklist_id,
                "问题标题": _clean_text(row.get("title")),
                "问题描述": _clean_text(row.get("description")),
                "整改建议": _clean_text(row.get("recommendation")),
            }
        )
        if len(suggestions) >= limit:
            break
    return suggestions


def load_medicheck_rules() -> list[dict[str, Any]]:
    rules_path = Path(
        os.getenv(
            "MEDIWRITER_MEDICHECK_RULES_PATH",
            str(Path(__file__).resolve().parents[1] / "MediCheck" / "config" / "checklist.json"),
        )
    ).expanduser()
    data = json.loads(rules_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"invalid MediCheck rules file: {rules_path}")
    return [item for item in data if isinstance(item, dict)]


def _database_url() -> str:
    load_mediwriter_env()
    return _clean_text(os.getenv("MEDIWRITER_MEDICHECK_DATABASE_URL") or os.getenv("MEDICHECK_DATABASE_URL"))


def _extract_patient_no(query_json: dict[str, Any]) -> str:
    pat_info = query_json.get("PatInfo")
    if not isinstance(pat_info, dict):
        return ""
    return _clean_text(pat_info.get("PatientNo") or pat_info.get("PationNo"))


def _enabled() -> bool:
    load_mediwriter_env()
    value = os.getenv("MEDIWRITER_ENABLE_MEDICHECK_SUGGESTIONS", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = _clean_text(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _format_datetime(value: Any, parsed: datetime) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return _clean_text(value) or parsed.strftime("%Y-%m-%d %H:%M:%S")


def _clean_text_list(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    return [_clean_text(item) for item in items if _clean_text(item)]
