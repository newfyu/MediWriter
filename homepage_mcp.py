from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

from blood_glucose_mcp import (
    DEFAULT_TIMEOUT_SECONDS,
    _call_tool_error_text,
    _clean_text,
    _load_his_agent_server_config,
    _log,
    _parse_tool_content,
    _read_int_env,
    _run_async,
)
from env_config import load_mediwriter_env


HOMEPAGE_DOCTOR_SIGNATURE_KEY = "病案首页医师签名"
HOMEPAGE_DOCTOR_SIGNATURE_FIELDS = ("科主任", "主任医师", "主治", "住院医师")


def enrich_query_with_homepage_doctors(query_json: dict[str, Any], logger: Any | None = None) -> dict[str, Any]:
    existing = query_json.get(HOMEPAGE_DOCTOR_SIGNATURE_KEY)
    if isinstance(existing, dict) and any(_clean_text(value) for value in existing.values()):
        return query_json

    if not _enabled():
        query_json.setdefault(HOMEPAGE_DOCTOR_SIGNATURE_KEY, {})
        return query_json

    patient_no = _extract_patient_no(query_json)
    if not patient_no:
        query_json[HOMEPAGE_DOCTOR_SIGNATURE_KEY] = {}
        _log(logger, "warning", "缺少 PatInfo.PatientNo，跳过病案首页医师签名查询")
        return query_json

    try:
        result = fetch_homepage_doctor_signatures(patient_no)
        query_json[HOMEPAGE_DOCTOR_SIGNATURE_KEY] = _normalize_homepage_doctor_signatures(result)
    except Exception as exc:
        query_json[HOMEPAGE_DOCTOR_SIGNATURE_KEY] = {}
        _log(logger, "warning", f"病案首页医师签名查询失败，已留空: {exc}")
    return query_json


def fetch_homepage_doctor_signatures(patient_no: str) -> dict[str, Any]:
    load_mediwriter_env()
    timeout_seconds = _read_int_env("MEDIWRITER_HOMEPAGE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
    return _run_async(_fetch_homepage_doctor_signatures_async, patient_no, timeout_seconds)


async def _fetch_homepage_doctor_signatures_async(patient_no: str, timeout_seconds: int) -> dict[str, Any]:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    server_config = _load_his_agent_server_config()
    env = dict(os.environ)
    env.update(server_config.get("env") or {})
    server = StdioServerParameters(
        command=server_config["command"],
        args=server_config.get("args") or [],
        cwd=server_config.get("cwd"),
        env=env,
    )
    timeout = timedelta(seconds=timeout_seconds)
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream, read_timeout_seconds=timeout) as session:
            await session.initialize()
            inpatient_no = await _lookup_latest_inpatient_no(session, patient_no, timeout)
            if not inpatient_no:
                return {}

            homepage = await _call_tool(
                session,
                "get_inpatient_homepage_readable",
                {"inpatient_no": inpatient_no},
                timeout,
            )
            homepage["InpatientNo"] = homepage.get("InpatientNo") or inpatient_no
            return homepage


async def _lookup_latest_inpatient_no(session: Any, patient_no: str, timeout: timedelta) -> str:
    search_result = await _call_tool(
        session,
        "search_inpatients",
        {"patient_no": patient_no, "current_only": False, "limit": 1},
        timeout,
    )
    patients = search_result.get("patients") or []
    if not isinstance(patients, list) or not patients:
        return ""
    first_patient = patients[0]
    if not isinstance(first_patient, dict):
        return ""
    return _clean_text(first_patient.get("inpatient_no"))


async def _call_tool(session: Any, name: str, arguments: dict[str, Any], timeout: timedelta) -> dict[str, Any]:
    result = await session.call_tool(name, arguments, read_timeout_seconds=timeout)
    if getattr(result, "isError", False):
        raise RuntimeError(_call_tool_error_text(result))
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    return _parse_tool_content(result)


def _normalize_homepage_doctor_signatures(result: Any) -> dict[str, str]:
    if not isinstance(result, dict):
        return {}

    direct_values = {
        field: _clean_text(result.get(field))
        for field in HOMEPAGE_DOCTOR_SIGNATURE_FIELDS
        if _clean_text(result.get(field))
    }
    if direct_values:
        return direct_values

    content = _clean_text(result.get("Content"))
    if not content:
        return {}

    values: dict[str, str] = {}
    for raw_part in content.replace("\n", "；").split("；"):
        part = raw_part.strip()
        if not part:
            continue
        for field in HOMEPAGE_DOCTOR_SIGNATURE_FIELDS:
            prefix = f"{field}:"
            if part.startswith(prefix):
                value = _clean_text(part[len(prefix):])
                if value:
                    values[field] = value
                break
    return values


def _extract_patient_no(query_json: dict[str, Any]) -> str:
    pat_info = query_json.get("PatInfo")
    if not isinstance(pat_info, dict):
        return ""
    return _clean_text(pat_info.get("PatientNo") or pat_info.get("PationNo"))


def _enabled() -> bool:
    load_mediwriter_env()
    value = os.getenv("MEDIWRITER_ENABLE_HOMEPAGE_DOCTOR_LOOKUP", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}
