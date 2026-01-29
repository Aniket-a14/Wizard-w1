import pandas as pd
import io
from fastapi import UploadFile, HTTPException
from ..config import settings

MAX_FILE_SIZE = 50 * 1024 * 1024 # 50MB

async def validate_csv(file: UploadFile) -> pd.DataFrame:
    # 1. Check Extension
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Invalid file type. Only CSV allowed.")
        
    # 2. Check Size (Streaming check would be better for massive files, but this is a start)
    # Getting size from spool isn't always reliable, relying on content read or headers
    # content = await file.read() # Warning: Reads into memory
    
    # Efficient approach: Read chunks or just trust read for now given memory constraint isn't strict yet
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    
    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large. Max size is {MAX_FILE_SIZE/1024/1024}MB")
        
    try:
        content = await file.read()
        df = pd.read_csv(io.BytesIO(content))
        
        # 3. Sanity Checks
        if df.empty:
            raise HTTPException(status_code=400, detail="CSV is empty.")
            
        # 4. Column Name Sanitization (Prevent eval injection via weird col names)
        df.columns = df.columns.astype(str).str.replace(r'[^\w\s]', '', regex=True)
        
        return df
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Malformed CSV: {str(e)}")
