import pandas as pd
import io
from typing import Dict, Any, Optional, Tuple
from app.core.exceptions import InvalidFileTypeError, DatasetNotFoundError

class DataService:
    """
    Service for handling dataset operations (Senior Data Engineer pattern).
    Manages loading, validation, and metadata extraction.
    """
    
    _instance = None
    _df: Optional[pd.DataFrame] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DataService, cls).__new__(cls)
        return cls._instance
    
    @property
    def df(self) -> pd.DataFrame:
        if self._df is None:
            raise DatasetNotFoundError()
        return self._df
        
    @df.setter
    def df(self, value: pd.DataFrame):
        self._df = value

    async def load_dataset(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """
        Load and validate a dataset from file content.
        
        Args:
            file_content: Raw bytes of the file
            filename: Name of the file for type checking
            
        Returns:
            Dict containing metadata about the loaded dataset
        """
        if not filename.endswith('.csv'):
            raise InvalidFileTypeError()
            
        try:
            # Read CSV with pandas
            df = pd.read_csv(io.BytesIO(file_content))
            
            # Data Engineering: Basic Validation & Cleaning
            # 1. Check for empty dataframe
            if df.empty:
                raise ValueError("The uploaded dataset is empty.")
                
            # 2. Store in memory (Global state for MVP)
            self._df = df
            
            # 3. Generate Metadata (Data Profiling)
            return self._generate_metadata(df, filename)
            
        except pd.errors.EmptyDataError:
            raise InvalidFileTypeError("The file contains no columns to parse from.")
        except Exception as e:
            raise InvalidFileTypeError(f"Failed to parse CSV: {str(e)}")

    def load_from_path(self, file_path: str) -> pd.DataFrame:
        """Load dataset from a local file path (for CLI usage)."""
        try:
            df = pd.read_csv(file_path)
            self._df = df
            return df
        except Exception as e:
            raise IOError(f"Could not read content from {file_path}: {e}")

    def _generate_metadata(self, df: pd.DataFrame, filename: str) -> Dict[str, Any]:
        """Generate comprehensive metadata for the dataset."""
        buffer = io.StringIO()
        df.info(buf=buffer)
        info_str = buffer.getvalue()
        
        # Calculate memory usage
        memory_usage = df.memory_usage(deep=True).sum() / 1024 / 1024  # MB
        
        return {
            "filename": filename,
            "rows": df.shape[0],
            "columns": df.shape[1],
            "column_names": df.columns.tolist(),
            "dtypes": df.dtypes.astype(str).to_dict(),
            "missing_values": df.isnull().sum().to_dict(),
            "memory_usage_mb": round(memory_usage, 2),
            "preview": df.head(5).to_dict(orient="records")
        }

    def get_dataframe(self) -> Optional[pd.DataFrame]:
        return self._df

    def perform_initial_profiling(self) -> str:
        """
        Perform initial automated EDA and return a natural language summary.
        """
        if self._df is None:
            return "No dataset loaded."
            
        df = self._df
        rows, cols = df.shape
        missing = df.isnull().sum().sum()
        duplicates = df.duplicated().sum()
        
        # Identify column types
        num_cols = df.select_dtypes(include=['number']).columns.tolist()
        cat_cols = df.select_dtypes(include=['object', 'category']).columns.tolist()
        
        summary = [
            f"**Dataset Overview**",
            f"- **Dimensions**: {rows} rows, {cols} columns",
            f"- **Missing Values**: {missing} total",
            f"- **Duplicates**: {duplicates} rows",
            f"",
            f"**Column Structure**",
            f"- **Numerical Columns ({len(num_cols)})**: {', '.join(num_cols[:5])}{'...' if len(num_cols) > 5 else ''}",
            f"- **Categorical Columns ({len(cat_cols)})**: {', '.join(cat_cols[:5])}{'...' if len(cat_cols) > 5 else ''}",
            f"",
            f"**Quick Stats**",
        ]
        
        if num_cols:
            summary.append(f"- Means: {df[num_cols].mean().to_dict()}")
        
        return "\n".join(summary)

data_service = DataService()
