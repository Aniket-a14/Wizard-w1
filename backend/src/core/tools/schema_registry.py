from typing import Any

import pandas as pd

from src.core.database import db_mgr
from src.utils.logging import logger


class SchemaRegistry:
    """
    Manages metadata, keys, and schemas for datasets uploaded in the workspace.
    Allows the agent to understand multi-file relational joins.
    """

    @classmethod
    def register_dataframe(cls, filename: str, df: pd.DataFrame):
        """Extracts schema, keys, and row counts from the dataframe and registers it in SQLite."""
        try:
            columns = df.columns.tolist()
            row_count = len(df)

            # Detect primary key heuristic
            primary_key = cls._detect_primary_key(df)

            # Extract data types for meta
            dtypes = {col: str(dtype) for col, dtype in df.dtypes.items()}
            meta = {
                "dtypes": dtypes,
                "null_counts": df.isnull().sum().to_dict(),
            }

            db_mgr.save_schema(
                filename=filename, columns=columns, row_count=row_count, primary_key=primary_key, meta=meta
            )
            logger.info("Dataset schema registered successfully", filename=filename, cols_count=len(columns))
        except Exception as e:
            logger.error("Failed to register dataframe schema", filename=filename, error=str(e))

    @classmethod
    def _detect_primary_key(cls, df: pd.DataFrame) -> str:
        """Heuristics to identify a likely primary key."""
        cols_lower = [c.lower() for c in df.columns]

        # 1. Exact match 'id' or 'index'
        for idx, col in enumerate(df.columns):
            if cols_lower[idx] in {"id", "index", "pk", "uuid"}:
                return col

        # 2. Heuristic `<something>_id` or `id_<something>` that is unique
        for col in df.columns:
            col_l = col.lower()
            if (col_l.endswith("_id") or col_l.startswith("id_") or col_l.endswith("id")) and df[col].is_unique:
                return col

        # 3. Fallback: first unique column
        for col in df.columns:
            # Skip floating point columns or columns with high null counts
            if df[col].isnull().sum() == 0 and df[col].is_unique:
                return col

        return ""

    @classmethod
    def get_join_suggestions(cls) -> list[dict[str, Any]]:
        """Analyzes all registered schemas and returns potential keys for joins."""
        schemas = db_mgr.get_schemas()
        if len(schemas) < 2:
            return []

        suggestions = []
        for i in range(len(schemas)):
            for j in range(i + 1, len(schemas)):
                s1 = schemas[i]
                s2 = schemas[j]

                # Check column name overlaps (ignoring case)
                overlap = []
                s1_name = s1["filename"].split(".")[0].lower()
                s1_singular = s1_name[:-1] if s1_name.endswith("s") else s1_name
                s2_name = s2["filename"].split(".")[0].lower()
                s2_singular = s2_name[:-1] if s2_name.endswith("s") else s2_name

                for c1 in s1["columns"]:
                    for c2 in s2["columns"]:
                        c1_l = c1.lower()
                        c2_l = c2.lower()
                        if c1_l == c2_l:
                            overlap.append((c1, c2))
                        # Check ID cross-reference (e.g. s1's user_id references s2's primary key 'id')
                        elif s2["primary_key"] and c2_l == s2["primary_key"].lower():
                            if c1_l == f"{s2_singular}_id" or c1_l == f"{s2_name}_id":
                                overlap.append((c1, c2))
                        elif s1["primary_key"] and c1_l == s1["primary_key"].lower():
                            if c2_l == f"{s1_singular}_id" or c2_l == f"{s1_name}_id":
                                overlap.append((c1, c2))

                if overlap:
                    suggestions.append(
                        {
                            "file1": s1["filename"],
                            "file2": s2["filename"],
                            "matching_columns": [{"col1": o[0], "col2": o[1]} for o in overlap],
                        }
                    )
        return suggestions

    @classmethod
    def get_workspace_schema_context(cls) -> str:
        """Returns a string description of all tables in the workspace for LLM context."""
        schemas = db_mgr.get_schemas()
        if not schemas:
            return ""

        context = "\n=== MULTI-FILE WORKSPACE SCHEMAS ===\n"
        for s in schemas:
            context += f"Table Name: {s['filename']}\n"
            context += f"  Dimensions: {s['row_count']} rows x {len(s['columns'])} columns\n"
            if s["primary_key"]:
                context += f"  Primary Key: {s['primary_key']}\n"

            columns_str_list = []
            for c in s["columns"]:
                dtype = s["meta"].get("dtypes", {}).get(c, "unknown")
                columns_str_list.append(f"{c} ({dtype})")
            cols_joined = ", ".join(columns_str_list)
            context += f"  Columns (and types): {cols_joined}\n\n"

        suggestions = cls.get_join_suggestions()
        if suggestions:
            context += "--- Potential Join Mappings ---\n"
            for sug in suggestions:
                mappings = ", ".join([f"{m['col1']} <-> {m['col2']}" for m in sug["matching_columns"]])
                context += f"- Link [{sug['file1']}] and [{sug['file2']}] via: {mappings}\n"
            context += "\n"

        return context
