from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
import io
from agent import interpret_and_execute
from data_tools import load_dataset

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state for the dataframe (single-user limitation)
# In a real multi-user app, this would be stored in a session or database
state = {
    "df": None
}

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str
    code: str
    image: str | None = None

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    
    try:
        content = await file.read()
        df = pd.read_csv(io.BytesIO(content))
        state["df"] = df
        
        return {
            "message": "Dataset loaded successfully",
            "filename": file.filename,
            "shape": df.shape,
            "columns": df.columns.tolist()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading file: {str(e)}")

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    if state["df"] is None:
        raise HTTPException(status_code=400, detail="No dataset loaded. Please upload a CSV file first.")
    
    try:
        result, code, image = interpret_and_execute(request.message, state["df"])
        return ChatResponse(response=result, code=code, image=image)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "ok"}
