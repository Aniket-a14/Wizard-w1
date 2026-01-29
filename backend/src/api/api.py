from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import time
import numpy as np
import pandas as pd


# Modular Imports
from src.core.agent.flow import science_agent
from src.utils.validation import validate_csv
from src.utils.logging import configure_logger, logger
from src.core.prompts import generate_system_context
from src.config import settings

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
        duration=process_time
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

# Global State
state = {"df": None}

# Test Mode Initialization
if settings.ENV == "test":
    # Pre-load a dummy dataset for contract tests to exercise the full logic
    state["df"] = pd.DataFrame({
        "A": np.random.randn(10),
        "B": np.random.randn(10)
    })
    logger.info("Test Mode: Mock dataset loaded.")

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="The analysis request from the user.")

class Message(BaseModel):
    detail: str

class ChatResponse(BaseModel):
    response: str
    code: str
    image: str | None = None

@app.post("/upload", responses={415: {"model": Message}, 400: {"model": Message}})
async def upload_file(file: UploadFile = File(...)):
    try:
        # strict validation
        df = await validate_csv(file)
        state["df"] = df
        
        # Context generation
        summary = generate_system_context(df)
        
        logger.info("Dataset uploaded", rows=len(df), filename=file.filename)
        
        return {
            "message": "Dataset loaded successfully",
            "filename": file.filename,
            "shape": df.shape,
            "columns": df.columns.tolist(),
            "summary": summary
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error("Upload failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat", response_model=ChatResponse, responses={412: {"model": Message}, 400: {"model": Message}})
async def chat(request: ChatRequest):
    if state["df"] is None:
        raise HTTPException(status_code=412, detail="No dataset loaded.")
    
    try:
        # Use Class-based Agent
        result, code, image = science_agent.run(request.message, state["df"])
        return ChatResponse(response=result, code=code, image=image)
        
    except Exception as e:
        logger.error("Chat failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "ok"}
