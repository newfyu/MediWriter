from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import clear_session_cookie, require_admin, set_session_cookie, verify_password
from .config import Settings
from .indexer import Indexer
from .parser import extract_first_json_input
from .queries import (
    RecordFilters,
    dashboard_breakdowns,
    dashboard_summary,
    dashboard_trends,
    command_info_analysis,
    create_template_test_input,
    delete_template_test_input,
    get_record,
    get_template_test_input,
    list_records,
    list_template_test_inputs,
    mark_template_test_input_run,
    update_template_test_input,
)
from .templates import load_template_file, save_template_file


class LoginPayload(BaseModel):
    username: str
    password: str


class TemplateConfigPayload(BaseModel):
    templates: list[dict[str, Any]] | None = None
    yaml_text: str | None = None


class TemplateTestInputCreatePayload(BaseModel):
    title: str
    input_json: str
    source_record_id: int | None = None
    source_filename: str | None = None
    doc_type: str | None = None
    doctor_name: str | None = None
    department: str | None = None


class TemplateTestInputUpdatePayload(BaseModel):
    title: str | None = None
    input_json: str | None = None


def filters_from_query(
    date_from: str | None = None,
    date_to: str | None = None,
    doctor_id: str | None = None,
    department: str | None = None,
    doc_type: str | None = None,
    source: str | None = None,
    status: str | None = None,
    q: str | None = None,
) -> RecordFilters:
    return RecordFilters(
        date_from=date_from or None,
        date_to=date_to or None,
        doctor_id=doctor_id or None,
        department=department or None,
        doc_type=doc_type or None,
        source=source or None,
        status=status or None,
        q=q or None,
    )


async def _run_index(indexer: Indexer) -> None:
    await asyncio.to_thread(indexer.scan_once)


async def _scheduler(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    indexer: Indexer = app.state.indexer
    await _run_index(indexer)
    while True:
        await asyncio.sleep(settings.refresh_interval_seconds)
        await _run_index(indexer)


def _http_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _model_data(payload: BaseModel) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    return payload.dict()


def _run_mediwriter_test(settings: Settings, input_json: str) -> dict[str, Any]:
    url = settings.test_request_base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": settings.test_request_model,
        "stream": False,
        "user": settings.test_request_user,
        "messages": [{"role": "user", "content": input_json + "\n@MediWriter"}],
    }
    headers = {
        "Authorization": f"Bearer {settings.test_request_api_key}",
        "Content-Type": "application/json",
    }
    started = time.perf_counter()
    try:
        with httpx.Client(
            timeout=settings.test_request_timeout_seconds,
            trust_env=False,
        ) as client:
            response = client.post(url, headers=headers, json=body)
            response.raise_for_status()
    except ImportError as exc:
        elapsed = time.perf_counter() - started
        return {
            "ok": False,
            "elapsed_seconds": elapsed,
            "raw_content": "",
            "parsed_items": [],
            "parse_error": None,
            "error": str(exc),
            "request_url": url,
        }
    except httpx.HTTPStatusError as exc:
        elapsed = time.perf_counter() - started
        return {
            "ok": False,
            "elapsed_seconds": elapsed,
            "raw_content": exc.response.text,
            "parsed_items": [],
            "parse_error": None,
            "error": f"模型服务返回 {exc.response.status_code}",
            "request_url": url,
        }
    except httpx.RequestError as exc:
        elapsed = time.perf_counter() - started
        return {
            "ok": False,
            "elapsed_seconds": elapsed,
            "raw_content": "",
            "parsed_items": [],
            "parse_error": None,
            "error": str(exc),
            "request_url": url,
        }

    elapsed = time.perf_counter() - started
    try:
        payload = response.json()
    except ValueError:
        return {
            "ok": False,
            "elapsed_seconds": elapsed,
            "raw_content": response.text,
            "parsed_items": [],
            "parse_error": None,
            "error": "模型服务返回内容不是 JSON",
            "request_url": url,
        }

    choices = payload.get("choices") if isinstance(payload, dict) else None
    first_choice = choices[0] if isinstance(choices, list) and choices else {}
    if not isinstance(first_choice, dict):
        first_choice = {}
    message = first_choice.get("message", {})
    if not isinstance(message, dict):
        message = {}
    raw_content = message.get("content", "")
    if not isinstance(raw_content, str):
        raw_content = json.dumps(raw_content, ensure_ascii=False)
    parsed_items: list[dict[str, Any]] = []
    parse_error: str | None = None
    try:
        parsed = json.loads(raw_content)
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict) and "key" in item and "value" in item:
                    parsed_items.append({"key": item.get("key"), "value": item.get("value")})
    except json.JSONDecodeError as exc:
        parse_error = f"返回内容不是有效 JSON: {exc.msg}"

    return {
        "ok": True,
        "elapsed_seconds": elapsed,
        "raw_content": raw_content,
        "parsed_items": parsed_items,
        "parse_error": parse_error,
        "error": None,
        "request_url": url,
    }


def create_app(settings: Settings | None = None, start_scheduler: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    indexer = Indexer(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task: asyncio.Task | None = None
        if start_scheduler:
            task = asyncio.create_task(_scheduler(app))
        try:
            yield
        finally:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="全流程病历辅助书写系统后台 API", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.indexer = indexer

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/api/auth/login")
    def login(payload: LoginPayload, response: Response):
        if payload.username != settings.admin_user or not verify_password(
            settings, payload.password
        ):
            raise HTTPException(status_code=401, detail="invalid username or password")
        set_session_cookie(settings, response, settings.admin_user)
        return {"username": settings.admin_user}

    @app.post("/api/auth/logout")
    def logout(response: Response):
        clear_session_cookie(settings, response)
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(user: Annotated[dict, Depends(require_admin)]):
        return user

    @app.get("/api/dashboard/summary")
    def summary(
        user: Annotated[dict, Depends(require_admin)],
        filters: Annotated[RecordFilters, Depends(filters_from_query)],
    ):
        return dashboard_summary(settings.index_db, filters)

    @app.get("/api/dashboard/trends")
    def trends(
        user: Annotated[dict, Depends(require_admin)],
        filters: Annotated[RecordFilters, Depends(filters_from_query)],
    ):
        return dashboard_trends(settings.index_db, filters)

    @app.get("/api/dashboard/breakdowns")
    def breakdowns(
        user: Annotated[dict, Depends(require_admin)],
        filters: Annotated[RecordFilters, Depends(filters_from_query)],
    ):
        return dashboard_breakdowns(settings.index_db, filters)

    @app.get("/api/command-info/analysis")
    def command_info(
        user: Annotated[dict, Depends(require_admin)],
        filters: Annotated[RecordFilters, Depends(filters_from_query)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=50),
    ):
        return command_info_analysis(settings.index_db, filters, page, page_size)

    @app.get("/api/records")
    def records(
        user: Annotated[dict, Depends(require_admin)],
        filters: Annotated[RecordFilters, Depends(filters_from_query)],
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=100),
    ):
        return list_records(settings.index_db, filters, page, page_size)

    @app.get("/api/records/{record_id}")
    def record(record_id: int, user: Annotated[dict, Depends(require_admin)]):
        item = get_record(settings.index_db, record_id)
        if not item:
            raise HTTPException(status_code=404, detail="record not found")
        return item

    @app.get("/api/records/{record_id}/raw")
    def raw_record(record_id: int, user: Annotated[dict, Depends(require_admin)]):
        item = get_record(settings.index_db, record_id)
        if not item:
            raise HTTPException(status_code=404, detail="record not found")
        path = Path(item["path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="raw file not found")
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"id": record_id, "filename": item["filename"], "content": text}

    @app.get("/api/records/{record_id}/input")
    def record_input(record_id: int, user: Annotated[dict, Depends(require_admin)]):
        item = get_record(settings.index_db, record_id)
        if not item:
            raise HTTPException(status_code=404, detail="record not found")
        path = Path(item["path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="raw file not found")
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            _, input_json = extract_first_json_input(text)
        except ValueError as exc:
            raise _http_error(exc) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {
            "id": record_id,
            "filename": item["filename"],
            "doc_type": item.get("doc_type"),
            "doctor_name": item.get("doctor_name"),
            "department": item.get("department"),
            "input_json": input_json,
        }

    @app.get("/api/templates/preset-dic")
    def preset_dic(user: Annotated[dict, Depends(require_admin)]):
        try:
            return load_template_file(settings.preset_template_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise _http_error(exc) from exc

    @app.put("/api/templates/preset-dic")
    def save_preset_dic(
        payload: TemplateConfigPayload,
        user: Annotated[dict, Depends(require_admin)],
    ):
        try:
            return save_template_file(
                settings.preset_template_path,
                templates=payload.templates,
                yaml_text=payload.yaml_text,
            )
        except ValueError as exc:
            raise _http_error(exc) from exc

    @app.get("/api/template-test-inputs")
    def template_test_inputs(
        user: Annotated[dict, Depends(require_admin)],
        q: str | None = None,
    ):
        return {"items": list_template_test_inputs(settings.index_db, q)}

    @app.post("/api/template-test-inputs")
    def create_test_input(
        payload: TemplateTestInputCreatePayload,
        user: Annotated[dict, Depends(require_admin)],
    ):
        try:
            return create_template_test_input(settings.index_db, **_model_data(payload))
        except ValueError as exc:
            raise _http_error(exc) from exc

    @app.patch("/api/template-test-inputs/{input_id}")
    def update_test_input(
        input_id: int,
        payload: TemplateTestInputUpdatePayload,
        user: Annotated[dict, Depends(require_admin)],
    ):
        try:
            updated = update_template_test_input(settings.index_db, input_id, **_model_data(payload))
        except ValueError as exc:
            raise _http_error(exc) from exc
        if not updated:
            raise HTTPException(status_code=404, detail="test input not found")
        return updated

    @app.delete("/api/template-test-inputs/{input_id}")
    def delete_test_input(input_id: int, user: Annotated[dict, Depends(require_admin)]):
        if not delete_template_test_input(settings.index_db, input_id):
            raise HTTPException(status_code=404, detail="test input not found")
        return {"ok": True}

    @app.post("/api/template-test-inputs/{input_id}/run")
    def run_test_input(input_id: int, user: Annotated[dict, Depends(require_admin)]):
        item = get_template_test_input(settings.index_db, input_id)
        if not item:
            raise HTTPException(status_code=404, detail="test input not found")
        result = _run_mediwriter_test(settings, item["input_json"])
        mark_template_test_input_run(settings.index_db, input_id)
        return result

    @app.get("/api/index/status")
    def index_status(user: Annotated[dict, Depends(require_admin)]):
        return indexer.status()

    @app.post("/api/index/refresh")
    def refresh_index(
        background_tasks: BackgroundTasks,
        user: Annotated[dict, Depends(require_admin)],
    ):
        if indexer.is_running():
            return {"status": "running"}
        background_tasks.add_task(indexer.scan_once)
        return {"status": "started"}

    if settings.frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets")

        @app.get("/{full_path:path}")
        def frontend(full_path: str, request: Request):
            candidate = settings.frontend_dist / full_path
            if full_path and candidate.exists() and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(settings.frontend_dist / "index.html")

    return app


app = create_app()
