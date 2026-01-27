from fastapi import HTTPException, status

class DatasetNotFoundError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found. Please upload a CSV file first."
        )

class InvalidFileTypeError(HTTPException):
    def __init__(self, detail: str = "Only CSV files are supported"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail
        )

class CodeExecutionError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Code execution failed: {detail}"
        )

class ModelError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI Model error: {detail}"
        )
