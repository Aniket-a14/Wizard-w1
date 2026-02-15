from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import time
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


# Modular Imports
from src.core.agent.flow import science_agent
from src.utils.validation import validate_csv
from src.utils.logging import configure_logger, logger
from src.core.prompts import generate_system_context
from src.core.reporting import reporting_engine

# Initialize Logging
configure_logger()

app = FastAPI(title="Wizard AI Agent", version="2.0.0")


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
        max_length=10000, # Increased for plans
        description="The analysis request from the user.",
    )
    mode: str = "planning" # "planning" or "fast"
    is_confirmed_plan: bool = False


class Message(BaseModel):
    detail: list[dict]


class ChatResponse(BaseModel):
    response: str
    code: str
    thought: str | None = None
    image: str | None = None
    status: str = "completed" # "completed" or "waiting_confirmation"


@app.post("/upload", responses={422: {"model": Message}, 400: {"model": Message}})
async def upload_file(file: UploadFile = File(...)):
    try:
        # strict validation
        df = await validate_csv(file)
        # Phase 1: Semantic Cleaning Stage
        cleaned_df, catalog, cleaning_summary = science_agent.clean_dataset(df)
        state["df"] = cleaned_df
        state["catalog"] = catalog

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
            "catalog": catalog
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error("Upload failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


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
            detail=[
                {"loc": ["state"], "msg": "No dataset loaded.", "type": "state_error"}
            ],
        )

    try:
        # Use Class-based Agent
        result, code, image, thought, status = science_agent.run(
            request.message, 
            state["df"], 
            mode=request.mode, 
            is_confirmed_plan=request.is_confirmed_plan,
            catalog=state.get("catalog")
        )
        return ChatResponse(
            response=result, 
            code=code, 
            image=image, 
            thought=thought,
            status=status
        )

    except Exception as e:
        logger.error("Chat failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/report")
async def generate_report():
    """Generates an executive summary of recent data analysis interactions."""
    report = reporting_engine.generate_executive_summary()
    return {"report": report}


@app.get("/health")
async def health_check():
    return {"status": "ok"}
