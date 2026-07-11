import io

import pandas as pd
from fastapi import HTTPException, UploadFile


MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


async def validate_csv(file: UploadFile) -> pd.DataFrame:
    # 1. Check Extension
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "loc": ["file"],
                    "msg": "Invalid file type. Only CSV allowed.",
                    "type": "value_error",
                }
            ],
        )

    # 2. Check Size (Streaming check would be better for massive files, but this is a start)
    # Getting size from spool isn't always reliable, relying on content read or headers
    # content = await file.read() # Warning: Reads into memory

    # Efficient approach: Read chunks or just trust read for now given memory constraint isn't strict yet
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)

    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max size is {MAX_FILE_SIZE / 1024 / 1024}MB",
        )

    try:
        content = await file.read()

        def parse_data(data: bytes, enc: str):
            # Decode the raw bytes into string strictly
            decoded = data.decode(enc, errors="strict")
            # Strip out any NUL bytes to prevent "line contains NUL" parser errors
            cleaned = decoded.replace("\x00", "")

            # Try default comma separator
            try:
                return pd.read_csv(io.StringIO(cleaned))
            except Exception:
                # Try semicolon separator
                try:
                    return pd.read_csv(io.StringIO(cleaned), sep=";")
                except Exception:
                    # Try tab separator
                    try:
                        return pd.read_csv(io.StringIO(cleaned), sep="\t")
                    except Exception:
                        # Fallback to python engine delimiter auto-detection
                        return pd.read_csv(io.StringIO(cleaned), sep=None, engine="python")

        # Prioritize encoding order based on null byte detection.
        # UTF-16 files contain null bytes for ASCII chars, which are absent in standard UTF-8 CSVs.
        encodings = (
            ["utf-16", "utf-8", "cp1252", "latin-1"] if b"\x00" in content else ["utf-8", "utf-16", "cp1252", "latin-1"]
        )

        df = None
        last_error = None
        for enc in encodings:
            try:
                df = parse_data(content, enc)
                break
            except Exception as e:
                last_error = e

        if df is None:
            raise last_error or Exception("Unable to parse CSV data.")

        # 3. Sanity Checks
        if df.empty:
            raise HTTPException(status_code=400, detail="CSV is empty.")

        # 4. Column Name Sanitization (Prevent eval injection via weird col names)
        df.columns = df.columns.astype(str).str.replace(r"[^\w\s]", "", regex=True)

        return df

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Malformed CSV: {str(e)}")
