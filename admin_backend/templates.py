from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml


VALID_MATCHES = {"exact", "contains"}


def _as_string_list(value: Any, field: str, index: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"第 {index + 1} 个模板的 {field} 必须是列表")
    normalized: list[str] = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是"}
    return bool(value)


def validate_templates(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("模板文件顶层必须是列表")

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index + 1} 个模板必须是对象")

        doc_type = str(item.get("DocType") or "").strip()
        if not doc_type:
            raise ValueError(f"第 {index + 1} 个模板缺少 DocType")
        if doc_type in seen:
            raise ValueError(f"DocType 重复: {doc_type}")
        seen.add(doc_type)

        template: dict[str, Any] = {
            "DocType": doc_type,
            "DicTemplate": _as_string_list(item.get("DicTemplate"), "DicTemplate", index),
        }

        match = str(item.get("DocTypeMatch") or "").strip()
        if match:
            if match not in VALID_MATCHES:
                raise ValueError(f"{doc_type} 的 DocTypeMatch 只能是 exact 或 contains")
            template["DocTypeMatch"] = match

        if "RuntimeSchemaFields" in item:
            fields = item.get("RuntimeSchemaFields")
            if not isinstance(fields, list):
                raise ValueError(f"{doc_type} 的 RuntimeSchemaFields 必须是列表")
            normalized_fields: list[dict[str, Any]] = []
            for field_index, field in enumerate(fields):
                if not isinstance(field, dict):
                    raise ValueError(f"{doc_type} 的第 {field_index + 1} 个运行时字段必须是对象")
                field_name = str(field.get("FieldName") or "").strip()
                if not field_name:
                    raise ValueError(f"{doc_type} 的第 {field_index + 1} 个运行时字段缺少 FieldName")
                normalized_field: dict[str, Any] = {"FieldName": field_name}
                for key in ("Description", "Position", "AnchorField"):
                    text = str(field.get(key) or "").strip()
                    if text:
                        normalized_field[key] = text
                normalized_field["Required"] = _as_bool(field.get("Required", True))
                normalized_field["Transient"] = _as_bool(field.get("Transient", True))
                normalized_fields.append(normalized_field)
            if normalized_fields:
                template["RuntimeSchemaFields"] = normalized_fields

        if "DayLimit" in item and item.get("DayLimit") not in ("", None):
            try:
                day_limit = int(item.get("DayLimit"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{doc_type} 的 DayLimit 必须是整数") from exc
            if day_limit < 0:
                raise ValueError(f"{doc_type} 的 DayLimit 不能小于 0")
            template["DayLimit"] = day_limit

        advise = str(item.get("TemplateAdvise") or "")
        if advise:
            template["TemplateAdvise"] = advise.rstrip()

        exclude = _as_string_list(item.get("Exclude"), "Exclude", index)
        if exclude:
            template["Exclude"] = exclude

        normalized.append(template)

    return normalized


def dump_templates(templates: list[dict[str, Any]]) -> str:
    return yaml.safe_dump(
        templates,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )


def load_template_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"模板文件不存在: {path}")
    yaml_text = path.read_text(encoding="utf-8")
    templates = validate_templates(yaml.safe_load(yaml_text))
    stat = path.stat()
    return {
        "path": str(path),
        "templates": templates,
        "yaml_text": dump_templates(templates),
        "updated_at": stat.st_mtime,
    }


def save_template_file(
    path: Path,
    *,
    templates: list[dict[str, Any]] | None = None,
    yaml_text: str | None = None,
) -> dict[str, Any]:
    if templates is None and yaml_text is None:
        raise ValueError("缺少模板内容")

    if yaml_text is not None:
        try:
            parsed = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc:
            raise ValueError(f"YAML 格式错误: {exc}") from exc
        normalized = validate_templates(parsed)
    else:
        normalized = validate_templates(templates)

    next_text = dump_templates(normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))

    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(next_text)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)

    return load_template_file(path)
