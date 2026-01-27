from fastapi import APIRouter, UploadFile, File, HTTPException
from app.services.data_service import data_service

router = APIRouter()

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Upload and validate a CSV dataset.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    content = await file.read()
    
    try:
        metadata = await data_service.load_dataset(content, file.filename)
        eda_summary = data_service.perform_initial_profiling()
        return {
            "message": "Dataset loaded successfully",
            "metadata": metadata,
            "eda_summary": eda_summary
        }
    except Exception as e:
        # Pass through expected service exceptions or wrap generic ones
        raise HTTPException(status_code=400, detail=str(e))
