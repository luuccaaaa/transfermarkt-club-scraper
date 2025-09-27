from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, validator

from . import pipeline

logger = logging.getLogger(__name__)

app = FastAPI(title="Transfermarkt Workflow API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


def serialise_path(path: Path) -> str:
    try:
        return str(path.relative_to(pipeline.DATA_DIR))
    except ValueError:
        return str(path)


class Job:
    def __init__(self, job_id: str, loop: asyncio.AbstractEventLoop) -> None:
        self.id = job_id
        self.loop = loop
        self.queue: asyncio.Queue[Optional[dict]] = asyncio.Queue()
        self.logs: List[dict] = []
        self.status: str = "pending"
        self.error: Optional[str] = None
        self.result: Optional[pipeline.WorkflowResult] = None
        self.created_at = datetime.utcnow().isoformat()
        self.lock = threading.Lock()

    def log(self, message: str) -> None:
        record = {
            "type": "log",
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
        }
        with self.lock:
            self.logs.append(record)
        self.loop.call_soon_threadsafe(self.queue.put_nowait, record)

    def set_status(self, status: str) -> None:
        with self.lock:
            self.status = status
        event = {"type": "status", "status": status, "timestamp": datetime.utcnow().isoformat()}
        self.loop.call_soon_threadsafe(self.queue.put_nowait, event)

    def finish(self, result: pipeline.WorkflowResult) -> None:
        with self.lock:
            self.result = result
            self.error = None
        self.set_status("completed")
        self.loop.call_soon_threadsafe(
            self.queue.put_nowait,
            {
                "type": "result",
                "status": "completed",
                "timestamp": datetime.utcnow().isoformat(),
                "data": self.result_payload(),
            },
        )
        self.loop.call_soon_threadsafe(self.queue.put_nowait, None)

    def fail(self, error: str) -> None:
        with self.lock:
            self.error = error
        self.set_status("failed")
        self.loop.call_soon_threadsafe(
            self.queue.put_nowait,
            {
                "type": "error",
                "status": "failed",
                "timestamp": datetime.utcnow().isoformat(),
                "error": error,
            },
        )
        self.loop.call_soon_threadsafe(self.queue.put_nowait, None)

    def result_payload(self) -> Optional[dict]:
        if not self.result:
            return None
        return {
            "teams": self.result.team_details,
            "club_ids_csv": serialise_path(self.result.club_ids_csv),
            "generated_csvs": [serialise_path(path) for path in self.result.generated_csvs],
            "augmented_csvs": [serialise_path(path) for path in self.result.augmented_csvs],
            "workbook": serialise_path(self.result.workbook_path),
            "selected_fields": self.result.selected_fields,
        }

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "error": self.error,
            "logs": self.logs,
            "result": self.result_payload(),
            "created_at": self.created_at,
        }


jobs: Dict[str, Job] = {}


class RunRequest(BaseModel):
    team_ids: List[str] = Field(default_factory=list, description="List of Transfermarkt club IDs")
    season_id: Optional[str] = Field(default=None, description="Optional season filter")
    fields: List[str] = Field(default_factory=list, description="Custom workbook field order")

    @validator("team_ids", pre=True)
    def _coerce_ids(cls, value):  # type: ignore[override]
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list):
            cleaned = []
            for item in value:
                if item is None:
                    continue
                item = str(item).strip()
                if item:
                    cleaned.append(item)
            return cleaned
        raise ValueError("team_ids must be an array or string")

    @validator("fields", pre=True)
    def _coerce_fields(cls, value):  # type: ignore[override]
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        raise ValueError("fields must be an array or string")


class RunResponse(BaseModel):
    job_id: str


async def launch_job(team_ids: List[str], season_id: Optional[str], fields: List[str]) -> Job:
    loop = asyncio.get_running_loop()
    job_id = uuid4().hex
    job = Job(job_id, loop)
    jobs[job_id] = job

    job.log(f"Received {len(team_ids)} club IDs")
    if fields:
        job.log(f"Selected workbook fields: {', '.join(fields)}")

    async def runner() -> None:
        job.set_status("running")
        try:
            result = await asyncio.to_thread(
                pipeline.run_workflow,
                team_ids,
                season_id=season_id or None,
                selected_fields=fields or None,
                logger=job.log,
            )
        except pipeline.WorkflowError as exc:
            job.fail(str(exc))
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("Workflow failed")
            job.fail(f"Unexpected error: {exc}")
        else:
            job.finish(result)

    asyncio.create_task(runner())
    return job


def sse_format(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@app.get("/api/fields")
async def list_fields() -> dict:
    return {
        "fields": [{"id": key, "label": label} for key, label in pipeline.AVAILABLE_FIELDS.items()],
        "default": list(pipeline.DEFAULT_FIELD_ORDER),
    }


@app.post("/api/run", response_model=RunResponse)
async def api_run(payload: RunRequest) -> RunResponse:
    if not payload.team_ids:
        raise HTTPException(status_code=400, detail="Provide at least one club ID")
    fields = [field for field in payload.fields if field in pipeline.AVAILABLE_FIELDS]
    job = await launch_job(payload.team_ids, payload.season_id, fields)
    return RunResponse(job_id=job.id)


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> JSONResponse:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(job.to_dict())


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str) -> StreamingResponse:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        yield sse_format({"type": "status", "status": job.status})
        while True:
            item = await job.queue.get()
            if item is None:
                break
            yield sse_format(item)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/download")
async def download(path: str) -> FileResponse:
    if not path:
        raise HTTPException(status_code=400, detail="Missing path parameter")
    target = (pipeline.DATA_DIR / path).resolve()
    try:
        target.relative_to(pipeline.DATA_DIR)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target, filename=target.name)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
