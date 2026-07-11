import asyncio
import os
import time
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.config import settings

# Modular Imports
from src.core.agent.flow import science_agent
from src.core.prompts import generate_system_context
from src.core.reporting import reporting_engine
from src.utils.logging import configure_logger, logger
from src.utils.validation import validate_csv


# Initialize Logging
configure_logger()

app = FastAPI(title="Wizard AI Agent", version="2.3.0")


# Middleware for Logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time

    logger.info(
        "Request processed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration=process_time,
    )
    return response


# Simple In-Memory Rate Limiter (no external dependencies)


_rate_limit_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_MAX_REQUESTS = 30  # per window
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMITED_PATHS = {"/chat", "/upload", "/ws/chat"}


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    if path in RATE_LIMITED_PATHS:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        # Clean old entries outside the window
        _rate_limit_store[client_ip] = [t for t in _rate_limit_store[client_ip] if now - t < RATE_LIMIT_WINDOW_SECONDS]
        if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_MAX_REQUESTS:
            logger.warning("Rate limit exceeded", client_ip=client_ip, path=path)
            return JSONResponse(status_code=429, content={"detail": "Too many requests. Please wait before retrying."})
        _rate_limit_store[client_ip].append(now)
    return await call_next(request)


# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Force all 422 validation errors to match our Message model."""
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


# Global State
state = {"df": None, "catalog": None}


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=10000,  # Increased for plans
        description="The analysis request from the user.",
    )
    mode: str = "planning"  # "planning" or "fast"
    is_confirmed_plan: bool = False


class Message(BaseModel):
    detail: list[dict]


class ChatResponse(BaseModel):
    response: str
    code: str
    thought: str | None = None
    image: str | None = None
    status: str = "completed"  # "completed" or "waiting_confirmation"


@app.post("/upload", responses={422: {"model": Message}, 400: {"model": Message}})
async def upload_file(file: UploadFile = File(...)):
    try:
        # strict validation
        df = await validate_csv(file)
        # Save raw/initial df to mounted workspace folder for sandbox access during cleaning
        csv_path = settings.WORKSPACE_DIR / "dataset.csv"
        feather_path = settings.WORKSPACE_DIR / "dataset.feather"
        df.to_csv(csv_path, index=False)
        df.to_feather(feather_path)

        # Initialize/start sandbox session so it has the raw 'df' loaded
        from src.core.tools.sandbox import sandbox_mgr
        if sandbox_mgr.container:
            await asyncio.to_thread(sandbox_mgr.cleanup)
        await asyncio.to_thread(sandbox_mgr.start_session)

        # Phase 1: Semantic Cleaning Stage (Offloaded to background thread)
        cleaned_df, catalog, cleaning_summary = await asyncio.to_thread(science_agent.clean_dataset, df)
        state["df"] = cleaned_df
        state["catalog"] = catalog

        # Save the final cleaned_df to the workspace, overwriting the raw version
        cleaned_df.to_csv(csv_path, index=False)
        cleaned_df.to_feather(feather_path)

        # Also save with original name to support multi-file joins
        if file.filename:
            import os

            clean_filename = os.path.basename(file.filename)
            original_path = settings.WORKSPACE_DIR / clean_filename
            cleaned_df.to_csv(original_path, index=False)

            # Register in Schema Registry
            from src.core.tools.schema_registry import SchemaRegistry

            SchemaRegistry.register_dataframe(clean_filename, cleaned_df)

        # Re-initialize sandbox session to load the final cleaned dataset for future user queries
        if sandbox_mgr.container:
            await asyncio.to_thread(sandbox_mgr.cleanup)
        await asyncio.to_thread(sandbox_mgr.start_session)

        # Context generation (now catalog-aware)
        summary = generate_system_context(cleaned_df, catalog=catalog)

        logger.info("Dataset uploaded and cleaned", rows=len(cleaned_df), filename=file.filename)

        return {
            "message": "Dataset loaded and semantically cleaned",
            "filename": file.filename,
            "shape": cleaned_df.shape,
            "columns": cleaned_df.columns.tolist(),
            "summary": summary,
            "cleaning_result": cleaning_summary,
            "catalog": catalog,
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error("Upload failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/data/preview")
async def get_data_preview(page: int = 1, per_page: int = 50, sort_by: str = None, sort_order: str = "asc"):
    if state["df"] is None:
        raise HTTPException(status_code=412, detail="No dataset loaded.")

    df = state["df"]
    total_rows = len(df)

    if sort_by and sort_by in df.columns:
        ascending = sort_order.lower() == "asc"
        df = df.sort_values(by=sort_by, ascending=ascending)

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page

    subset = df.iloc[start_idx:end_idx]

    # Clean NaNs and Infs for JSON validation
    subset_clean = subset.replace({float("nan"): None, float("inf"): None, float("-inf"): None})
    records = subset_clean.to_dict(orient="records")

    return {
        "page": page,
        "per_page": per_page,
        "total_rows": total_rows,
        "columns": df.columns.tolist(),
        "data": records,
    }


@app.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        412: {"model": Message},
        422: {"model": Message},
        400: {"model": Message},
    },
)
async def chat(request: ChatRequest):
    if state["df"] is None:
        raise HTTPException(
            status_code=412,
            detail=[{"loc": ["state"], "msg": "No dataset loaded.", "type": "state_error"}],
        )

    try:
        # Use Class-based Agent in a background thread to prevent blocking
        result, code, image, thought, status = await asyncio.to_thread(
            science_agent.run,
            request.message,
            state["df"],
            request.mode,
            request.is_confirmed_plan,
            state.get("catalog"),
        )
        return ChatResponse(response=result, code=code, image=image, thought=thought, status=status)

    except Exception as e:
        logger.error("Chat failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/report")
async def generate_report():
    """Generates an executive summary of recent data analysis interactions."""
    report = reporting_engine.generate_executive_summary()
    return {"report": report}


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message")
            mode = data.get("mode", "planning")
            is_confirmed_plan = data.get("is_confirmed_plan", False)

            # For resumed search
            is_tool_approved = data.get("approved", None)
            pending_tool = data.get("tool", None)
            pending_query = data.get("query", None)

            if not message:
                continue

            if state["df"] is None:
                await websocket.send_json({"type": "error", "content": "No dataset loaded."})
                continue

            # Start/Resume workflow
            from src.core.agent.langgraph_agent import WorkflowState, langgraph_agent

            workflow_state = WorkflowState(message, state["df"], mode=mode, catalog=state.get("catalog"))

            if is_tool_approved is not None and pending_tool == "web_search":
                # Resuming from web search approval
                workflow_state.status = "waiting_approval"
                workflow_state.pending_tool_approval = {"tool": "web_search", "query": pending_query}
                await websocket.send_json({"type": "status", "content": "🔍 Resuming planning node..."})
                workflow_state = await asyncio.to_thread(
                    langgraph_agent.step_execute_search, workflow_state, is_tool_approved
                )
            elif is_confirmed_plan:
                # Resuming from plan execution approval
                workflow_state.plan = message
                workflow_state.status = "executing"
            else:
                workflow_state.status = "init"

            # Run graph workflow step by step
            if workflow_state.status == "init":
                await websocket.send_json({"type": "status", "content": "🧠 Wizard is planning the analysis..."})
                workflow_state.status = "planning"
                workflow_state = await asyncio.to_thread(langgraph_agent.step_plan, workflow_state)

                if workflow_state.thought:
                    await websocket.send_json({"type": "thought", "content": workflow_state.thought})

                # Check if paused for approval
                if workflow_state.status == "waiting_approval":
                    await websocket.send_json(
                        {
                            "type": "approval_required",
                            "status": "waiting_confirmation",
                            "tool": workflow_state.pending_tool_approval.get("tool"),
                            "prompt": workflow_state.pending_tool_approval.get("prompt"),
                            "plan": workflow_state.plan,
                            "query": workflow_state.pending_tool_approval.get("query"),
                        }
                    )
                    continue

            # Coder & Exec Loop
            while workflow_state.status in ["executing", "correcting"]:
                if workflow_state.status == "correcting":
                    await websocket.send_json(
                        {
                            "type": "status",
                            "content": f"🔄 Self-correction: fixing execution error (Attempt {workflow_state.retry_count})...",
                        }
                    )
                    workflow_state = await asyncio.to_thread(langgraph_agent.step_correct_error, workflow_state)
                    if workflow_state.status == "error":
                        break

                await websocket.send_json(
                    {
                        "type": "status",
                        "content": f"💻 Generating Python code (Attempt {workflow_state.retry_count + 1})...",
                    }
                )
                workflow_state = await asyncio.to_thread(langgraph_agent.step_code_generate, workflow_state)

                if workflow_state.code:
                    await websocket.send_json({"type": "code", "content": workflow_state.code})

                await websocket.send_json(
                    {"type": "status", "content": "🐳 Running code inside persistent Docker sandbox..."}
                )

                # Define thread-safe stdout streaming callback
                loop = asyncio.get_running_loop()

                def stdout_callback(text):
                    cleaned_text = text.strip()
                    if cleaned_text:
                        asyncio.run_coroutine_threadsafe(
                            websocket.send_json({"type": "status", "content": f"💻 Output: {cleaned_text}"}), loop
                        )

                workflow_state = await asyncio.to_thread(
                    langgraph_agent.step_execute_code, workflow_state, stdout_callback
                )

            if workflow_state.status == "error":
                await websocket.send_json(
                    {
                        "type": "final",
                        "response": f"Execution failed after maximum retries. Final error:\n{workflow_state.error}",
                        "code": workflow_state.code,
                        "status": "completed",
                    }
                )
                continue

            # Evaluator & Council
            if workflow_state.status == "evaluating":
                await websocket.send_json(
                    {"type": "status", "content": "🛡️ The Council is reviewing the analysis results..."}
                )
                workflow_state = await langgraph_agent.step_evaluate(workflow_state)

            # Scan response text for saved files
            import re

            saved_files = []
            try:
                matches = re.findall(
                    r"([a-zA-Z0-9_\-\.]+\.(?:csv|xlsx|xls|png|jpg|feather|json))", workflow_state.result
                )
                for m in matches:
                    if (settings.WORKSPACE_DIR / m).exists() and m not in {"dataset.csv", "dataset.feather"}:
                        saved_files.append(m)
            except Exception:
                pass

            # Final output
            await websocket.send_json(
                {
                    "type": "final",
                    "response": workflow_state.result,
                    "code": workflow_state.code,
                    "image": workflow_state.image,
                    "status": "completed",
                    "downloads": list(set(saved_files)),
                }
            )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error("WebSocket chat crashed", error=str(e))
        try:
            await websocket.send_json({"type": "error", "content": f"Server error: {e}"})
        except Exception:
            pass


@app.get("/workspace/files")
async def list_workspace_files():
    files = []
    if not settings.WORKSPACE_DIR.exists():
        return {"files": []}

    for root, dirs, filenames in os.walk(settings.WORKSPACE_DIR):
        for f in filenames:
            full_path = Path(root) / f
            rel_path = full_path.relative_to(settings.WORKSPACE_DIR)

            # Skip hidden files
            if f.startswith("."):
                continue

            ext = full_path.suffix.lower()
            file_type = "file"
            if ext in [".png", ".jpg", ".jpeg", ".webp", ".html"]:
                file_type = "image"
            elif ext == ".csv":
                file_type = "csv"
            elif ext in [".json", ".txt", ".md"]:
                file_type = "text"
            elif ext == ".feather":
                file_type = "binary"

            files.append(
                {
                    "name": f,
                    "path": str(rel_path).replace("\\", "/"),
                    "size": full_path.stat().st_size,
                    "type": file_type,
                }
            )
    return {"files": files}


app.mount("/workspace/static", StaticFiles(directory=str(settings.WORKSPACE_DIR)), name="workspace_static")


@app.get("/sandbox/variables")
async def get_sandbox_variables():
    from src.core.tools.sandbox import sandbox_mgr

    variables = await asyncio.to_thread(sandbox_mgr.inspect_variables)
    return variables


@app.post("/sandbox/interrupt")
async def interrupt_sandbox():
    from src.core.tools.sandbox import sandbox_mgr

    await asyncio.to_thread(sandbox_mgr.interrupt)
    return {"status": "interrupted"}


@app.post("/sandbox/variables/export/{name}")
async def export_sandbox_variable(name: str):
    import os

    safe_name = os.path.basename(name)
    from src.core.tools.sandbox import sandbox_mgr

    # Verify variable exists in sandbox variables
    variables = await asyncio.to_thread(sandbox_mgr.inspect_variables)
    if safe_name not in variables:
        raise HTTPException(status_code=404, detail=f"Variable '{safe_name}' not found in sandbox memory.")

    # Run a small code block inside sandbox to export the variable to workspace
    export_code = f"""
import pandas as pd
if '{safe_name}' in globals():
    val = globals()['{safe_name}']
    if isinstance(val, pd.DataFrame):
        val.to_csv('/workspace/{safe_name}.csv', index=False)
    elif isinstance(val, pd.Series):
        val.to_frame().to_csv('/workspace/{safe_name}.csv', index=False)
    else:
        pd.DataFrame(list(val) if isinstance(val, (set, list, tuple)) else [val]).to_csv('/workspace/{safe_name}.csv', index=False)
"""
    await asyncio.to_thread(sandbox_mgr.run_code, export_code)
    return {"filename": f"{safe_name}.csv"}


@app.delete("/data/files/{filename}")
async def delete_workspace_file(filename: str):
    import os

    safe_filename = os.path.basename(filename)
    if safe_filename in {"dataset.csv", "dataset.feather"}:
        raise HTTPException(status_code=400, detail="Cannot delete core session dataset.")

    file_path = settings.WORKSPACE_DIR / safe_filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    try:
        os.remove(file_path)
        return {"message": f"File '{safe_filename}' deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
