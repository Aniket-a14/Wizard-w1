"""Semantic profiling of a DataFrame.

Profiling now runs against a bounded sample. The previous implementation called
``nunique()`` and a full outlier scan on every column of the full frame, which is
several passes over the data on every upload -- fine at 5,000 rows, minutes at
5,000,000.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.config import settings

from .stats import StatisticalToolkit


class CatalogEngine:
    """Detects semantic types and per-column quality metrics."""

    SEMANTIC_PATTERNS = {
        "email": r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
        "url": r"^https?://[^\s]+$",
        "currency": r"^[$€£¥]\s?[\d,]+(\.\d+)?$",
        "date": r"^\d{4}-\d{2}-\d{2}|^\d{2}/\d{2}/\d{4}",
        "phone": r"^(\+\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}$",
        "ip_address": r"^\d{1,3}(\.\d{1,3}){3}$",
    }

    NAME_HINTS = (
        ("identifier", ("id", "uuid", "guid", "pk", "key", "code")),
        ("financial", ("price", "cost", "amount", "revenue", "salary", "budget", "profit", "fee")),
        ("temporal", ("date", "time", "timestamp", "year", "month", "day", "created", "updated")),
        ("geospatial", ("lat", "lon", "lng", "coord", "city", "country", "region", "postal", "zip")),
        ("personal", ("name", "email", "phone", "ssn", "address", "birth")),
    )

    @classmethod
    def analyze(cls, df: pd.DataFrame, sample_rows: int | None = None) -> dict[str, Any]:
        """Profiles the frame, sampling when it exceeds the configured budget."""
        limit = sample_rows or settings.PROFILE_SAMPLE_ROWS
        sample = df.sample(n=limit, random_state=0) if len(df) > limit else df
        sampled = len(sample) < len(df)

        total_cells = int(df.size)
        total_missing = int(df.isnull().sum().sum()) if total_cells else 0

        catalog: dict[str, Any] = {
            "columns": {},
            "global_quality": {
                "total_missing": total_missing,
                "completeness_score": round((1 - total_missing / total_cells) * 100, 2) if total_cells else 100.0,
                "rows": int(len(df)),
                "sampled": sampled,
                "sample_rows": int(len(sample)),
            },
        }

        for column in df.columns:
            catalog["columns"][str(column)] = cls._analyze_column(sample, str(column))
        return catalog

    # ------------------------------------------------------------------ #
    @classmethod
    def _analyze_column(cls, df: pd.DataFrame, column: str) -> dict[str, Any]:
        series = df[column]
        row_count = len(df) or 1

        missing_pct = round(float(series.isnull().sum()) / row_count * 100, 2)
        try:
            unique_count = int(series.nunique(dropna=True))
        except TypeError:
            unique_count = -1  # unhashable contents

        outliers: dict[str, Any] = {}
        if pd.api.types.is_numeric_dtype(series.dtype) and series.notna().any():
            try:
                info = StatisticalToolkit.detect_outliers(df, column)
                outliers = {"count": info["outlier_count"], "percentage": info["outlier_percentage"]}
            except Exception:
                outliers = {}

        return {
            "native_dtype": str(series.dtype),
            "semantic_type": cls._detect_semantic_type(series),
            "quality": {
                "missing_percentage": missing_pct,
                "unique_values": unique_count,
                "outliers": outliers,
            },
        }

    @classmethod
    def _detect_semantic_type(cls, series: pd.Series) -> str:
        name = str(series.name).lower()
        for semantic_type, hints in cls.NAME_HINTS:
            if any(hint in name for hint in hints):
                return semantic_type

        if pd.api.types.is_datetime64_any_dtype(series.dtype):
            return "temporal"
        if pd.api.types.is_bool_dtype(series.dtype):
            return "boolean"

        sample = series.dropna().astype(str).head(100)
        if sample.empty:
            return "empty"

        for semantic_type, pattern in cls.SEMANTIC_PATTERNS.items():
            try:
                if sample.str.match(pattern).mean() > 0.6:
                    return semantic_type
            except Exception:
                # Defensive: odd dtypes can make the vectorised match raise.
                continue

        if pd.api.types.is_numeric_dtype(series.dtype):
            return "numeric"
        return "categorical" if series.nunique(dropna=True) <= max(2, len(sample) // 4) else "text"
