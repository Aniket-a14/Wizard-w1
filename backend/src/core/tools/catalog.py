import pandas as pd
import numpy as np
import re
from typing import Dict, List, Any
from .stats import StatisticalToolkit

class CatalogEngine:
    """
    Analyzes DataFrames to extract semantic meaning, quality metrics,
    and business ontology hints.
    """

    SEMANTIC_PATTERNS = {
        "email": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
        "currency": r"^[$€£¥]\d+",
        "url": r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+",
        "date": r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}",
        "phone": r"(\+\d{1,2}\s)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}"
    }

    @classmethod
    def analyze(cls, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Performs a full semantic and quality audit of the dataframe.
        """
        catalog = {
            "columns": {},
            "global_quality": {
                "total_missing": int(df.isnull().sum().sum()),
                "completeness_score": round((1 - df.isnull().sum().sum() / df.size) * 100, 2) if df.size > 0 else 0
            }
        }

        for col in df.columns:
            catalog["columns"][col] = cls._analyze_column(df, col)

        return catalog

    @classmethod
    def _analyze_column(cls, df: pd.DataFrame, col: str) -> Dict[str, Any]:
        series = df[col]
        dtype = str(series.dtype)
        
        # 1. Quality Metrics
        missing_pct = round((series.isnull().sum() / len(df)) * 100, 2)
        unique_count = series.nunique()
        
        # 2. Semantic Type Detection
        semantic_type = cls._detect_semantic_type(series)
        
        # 3. Statistical Hints (from existing toolkit)
        outliers = {}
        if pd.api.types.is_numeric_dtype(series.dtype):
            stats_info = StatisticalToolkit.detect_outliers(df, col)
            outliers = {
                "count": stats_info["outlier_count"],
                "percentage": stats_info["outlier_percentage"]
            }

        return {
            "native_dtype": dtype,
            "semantic_type": semantic_type,
            "quality": {
                "missing_percentage": missing_pct,
                "unique_values": unique_count,
                "outliers": outliers
            }
        }

    @classmethod
    def _detect_semantic_type(cls, series: pd.Series) -> str:
        """Heuristic-based semantic type detection."""
        # Drop NAs for detection
        sample = series.dropna().astype(str).head(100)
        if sample.empty:
            return "empty"

        # Check column name first
        name_lower = str(series.name).lower()
        if any(kw in name_lower for kw in ["id", "uuid", "pk"]):
            return "identifier"
        if any(kw in name_lower for kw in ["price", "cost", "amount", "revenue"]):
            return "financial"
        if any(kw in name_lower for kw in ["date", "time", "timestamp", "year"]):
            return "temporal"
        if any(kw in name_lower for kw in ["lat", "lon", "coord", "city", "country"]):
            return "geospatial"

        # Check content patterns
        for sem_type, pattern in cls.SEMANTIC_PATTERNS.items():
            if sample.str.match(pattern).mean() > 0.5:
                return sem_type

        return "generic"
