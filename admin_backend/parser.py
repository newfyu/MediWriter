from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


TIME_RE = re.compile(r"(\d+(?:\.\d+)?)\s*s\s*$", re.IGNORECASE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_NAME_RE = re.compile(r"^\d{2}-\d{2}-\d{2}$")


@dataclass
class FilenameInfo:
    doctor_id: str | None
    doctor_name: str | None
    timestamp: datetime | None


@dataclass
class ParsedRecord:
    path: Path
    source: str
    filename: str
    parse_status: str
    parse_error: str | None
    doctor_id: str | None
    doctor_name: str | None
    department: str | None
    patient_department: str | None
    doc_type: str | None
    command_info: str | None
    record_time: str | None
    record_date: str | None
    record_hour: int | None
    elapsed_seconds: float | None
    input_chars: int
    output_chars: int
    total_chars: int


def parse_filename(filename: str) -> FilenameInfo:
    stem = filename[:-4] if filename.endswith(".txt") else filename
    parts = stem.split("_")
    timestamp = None
    identity_parts = parts

    if len(parts) >= 3 and DATE_RE.match(parts[-2]) and TIME_NAME_RE.match(parts[-1]):
        try:
            timestamp = datetime.strptime(
                f"{parts[-2]} {parts[-1].replace('-', ':')}", "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            timestamp = None
        identity_parts = parts[:-2]

    identity_parts = [part for part in identity_parts if part != ""]
    if not identity_parts:
        return FilenameInfo(None, None, timestamp)

    if identity_parts == ["test", "user"]:
        return FilenameInfo("test_user", "test_user", timestamp)

    if len(identity_parts) >= 2:
        doctor_id = identity_parts[-1]
        doctor_name = "_".join(identity_parts[:-1]) or None
    else:
        doctor_id = identity_parts[0]
        doctor_name = None if doctor_id.isdigit() else doctor_id

    return FilenameInfo(doctor_id=doctor_id or None, doctor_name=doctor_name, timestamp=timestamp)


def _raw_decode_json_objects(text: str) -> tuple[list[tuple[Any, int, int]], str]:
    decoder = json.JSONDecoder()
    objects: list[tuple[Any, int, int]] = []
    pos = 0
    length = len(text)
    while pos < length:
        while pos < length and text[pos].isspace():
            pos += 1
        if pos >= length or text[pos] != "{":
            break
        obj, end = decoder.raw_decode(text, pos)
        objects.append((obj, pos, end))
        pos = end
    return objects, text[pos:]


def extract_first_json_input(text: str) -> tuple[dict[str, Any], str]:
    text = text.lstrip("\ufeff")
    objects, _ = _raw_decode_json_objects(text)
    if not objects:
        raise ValueError("no JSON object found")

    first_obj, _, _ = objects[0]
    if not isinstance(first_obj, dict):
        raise ValueError("first JSON object is not an object")

    input_json = json.dumps(first_obj, ensure_ascii=False, indent=2)
    return first_obj, input_json


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return str(value).strip() or None


def _elapsed_from_tail(tail: str) -> float | None:
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line:
            continue
        match = TIME_RE.search(line)
        if match:
            return float(match.group(1))
    return None


def parse_record_file(path: Path, source: str) -> ParsedRecord:
    filename_info = parse_filename(path.name)
    record_time = filename_info.timestamp.isoformat(sep=" ") if filename_info.timestamp else None
    record_date = filename_info.timestamp.date().isoformat() if filename_info.timestamp else None
    record_hour = filename_info.timestamp.hour if filename_info.timestamp else None

    try:
        text = path.read_text(encoding="utf-8", errors="ignore").lstrip("\ufeff")
        if not text.strip():
            raise ValueError("empty file")
        objects, tail = _raw_decode_json_objects(text)
        if not objects:
            raise ValueError("no JSON object found")

        first_obj, first_start, first_end = objects[0]
        second_raw = ""
        second_end = first_end
        if len(objects) >= 2:
            _, second_start, second_end = objects[1]
            second_raw = text[second_start:second_end]
            tail = text[second_end:]

        if not isinstance(first_obj, dict):
            raise ValueError("first JSON object is not an object")

        oper_info = first_obj.get("OperInfo") or {}
        pat_info = first_obj.get("PatInfo") or {}
        doctor_id = _as_text(oper_info.get("OperCode")) or filename_info.doctor_id
        doctor_name = _as_text(oper_info.get("OperName")) or filename_info.doctor_name
        department = _as_text(oper_info.get("LoginDeptName"))
        patient_department = _as_text(pat_info.get("DeptName"))
        doc_type = _as_text(first_obj.get("DocType"))
        command_info = _as_text(first_obj.get("CommandInfo"))
        first_raw = text[first_start:first_end]
        input_chars = len(first_raw)
        output_chars = len(second_raw)
        elapsed_seconds = _elapsed_from_tail(tail)

        return ParsedRecord(
            path=path,
            source=source,
            filename=path.name,
            parse_status="ok",
            parse_error=None,
            doctor_id=doctor_id,
            doctor_name=doctor_name,
            department=department,
            patient_department=patient_department,
            doc_type=doc_type,
            command_info=command_info,
            record_time=record_time,
            record_date=record_date,
            record_hour=record_hour,
            elapsed_seconds=elapsed_seconds,
            input_chars=input_chars,
            output_chars=output_chars,
            total_chars=input_chars + output_chars,
        )
    except Exception as exc:
        return ParsedRecord(
            path=path,
            source=source,
            filename=path.name,
            parse_status="error",
            parse_error=str(exc),
            doctor_id=filename_info.doctor_id,
            doctor_name=filename_info.doctor_name,
            department=None,
            patient_department=None,
            doc_type=None,
            command_info=None,
            record_time=record_time,
            record_date=record_date,
            record_hour=record_hour,
            elapsed_seconds=None,
            input_chars=0,
            output_chars=0,
            total_chars=0,
        )
