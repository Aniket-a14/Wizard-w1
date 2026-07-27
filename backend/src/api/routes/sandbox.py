"""Sandbox introspection and control."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import get_session, require_api_key
from src.api.schemas import JobResponse, VariablesResponse
from src.core.infra.queue import get_queue
from src.core.security.code_guard import is_safe_identifier
from src.core.session import Session
from src.core.tools import runtime as runtime_backend


router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])
# Jobs are not sandbox-scoped, so they get their own prefix.
jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/variables", response_model=VariablesResponse)
async def list_variables(session: Session = Depends(get_session)) -> VariablesResponse:
    """Variables currently live in this session's sandbox namespace."""
    variables = await asyncio.to_thread(session.executor.inspect_variables)
    return VariablesResponse(
        variables=variables,
        sandbox_available=runtime_backend.active_backend() == "docker",
    )


@router.post("/interrupt", dependencies=[Depends(require_api_key)])
async def interrupt(session: Session = Depends(get_session)) -> dict:
    """Signals the running cell without destroying the container."""
    interrupted = await asyncio.to_thread(session.executor.interrupt)
    return {"status": "interrupted" if interrupted else "nothing_running"}


@router.post("/variables/{name}/export", dependencies=[Depends(require_api_key)])
async def export_variable(name: str, session: Session = Depends(get_session)) -> dict:
    """Writes a sandbox variable to the session workspace as CSV."""
    # The name is interpolated into generated source, so it must be a bare
    # identifier. The previous version only applied os.path.basename, which does
    # not prevent quote-breaking.
    if not is_safe_identifier(name):
        raise HTTPException(status_code=400, detail="Variable names must be plain Python identifiers.")

    variables = await asyncio.to_thread(session.executor.inspect_variables)
    if name not in variables:
        raise HTTPException(status_code=404, detail=f"No variable named '{name}' in the sandbox.")

    export_code = (
        "import pandas as _pd\n"
        f"_value = {name}\n"
        "if isinstance(_value, _pd.DataFrame):\n"
        f"    _value.to_csv('/workspace/{name}.csv', index=False)\n"
        "elif isinstance(_value, _pd.Series):\n"
        f"    _value.to_frame().to_csv('/workspace/{name}.csv', index=False)\n"
        "else:\n"
        "    _rows = list(_value) if isinstance(_value, (list, tuple, set)) else [_value]\n"
        f"    _pd.DataFrame(_rows).to_csv('/workspace/{name}.csv', index=False)\n"
        f"print('exported {name}.csv')\n"
    )

    result = await asyncio.to_thread(session.executor.execute, export_code, None)
    if not result.ok:
        raise HTTPException(status_code=400, detail=f"Export failed: {result.output[:400]}")
    return {"filename": f"{name}.csv"}


@jobs_router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str) -> JobResponse:
    job = get_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    payload = job.to_dict()
    return JobResponse(
        id=payload["id"],
        kind=payload["kind"],
        status=payload["status"],
        progress=payload["progress"],
        message=payload["message"],
        error=payload["error"],
        result=payload["result"],
    )
