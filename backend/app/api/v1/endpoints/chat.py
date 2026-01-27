from fastapi import APIRouter, HTTPException, Depends
from app.services.agent_service import agent_service
from app.services.data_service import data_service
from app.models.chat import ChatRequest, ChatResponse
from app.core.exceptions import DatasetNotFoundError

from app.core.logger import logger

router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Process a natural language query on the loaded dataset.
    """
    logger.info(f"Chat request received: {request.message[:50]}...")
    
    # 1. Dependency Check: Ensure dataset is loaded
    try:
        df = data_service.df
    except DatasetNotFoundError:
        logger.warning("Chat attempted without loaded dataset.")
        raise HTTPException(
            status_code=400, 
            detail="No dataset loaded. Please upload a CSV file first via /upload."
        )

    # 2. Agent Execution
    try:
        result, code, image = await agent_service.interpret_and_execute(request.message, df)
        logger.info("Chat response generated successfully.")
        return ChatResponse(response=result, code=code, image=image)
    except Exception as e:
        logger.error(f"Chat execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
