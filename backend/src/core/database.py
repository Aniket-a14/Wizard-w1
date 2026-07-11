import json
import sqlite3
import numpy as np
from typing import List, Dict, Any, Optional
from src.config import settings
from src.utils.logging import logger

class DatabaseManager:
    """
    Unified SQLite database manager for semantic cache, trajectories memory, and feedbacks.
    Includes schema migration capabilities and schema-hash query indexing.
    """
    def __init__(self):
        self.db_path = settings.DATA_DIR / "wizard.db"
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Creates tables if they do not exist, and runs schema migrations if needed."""
        try:
            with self._get_connection() as conn:
                # 1. Semantic Cache Table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS semantic_cache (
                        query TEXT PRIMARY KEY,
                        schema_hash TEXT,
                        columns TEXT,
                        code TEXT,
                        embedding BLOB
                    )
                """)
                # 2. Trajectories Memory Table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS trajectories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        instruction TEXT,
                        schema_hash TEXT,
                        columns TEXT,
                        failed_code TEXT,
                        error_message TEXT,
                        corrected_code TEXT,
                        embedding BLOB
                    )
                """)
                # 3. Feedbacks Table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS feedbacks (
                        task TEXT PRIMARY KEY,
                        code TEXT,
                        embedding BLOB
                    )
                """)
                # 4. Working Memory Table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS working_memory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL,
                        instruction TEXT,
                        plan TEXT,
                        code TEXT,
                        result TEXT,
                        meta TEXT
                    )
                """)
                
                # Check for migrations
                # Check semantic_cache
                cursor = conn.execute("PRAGMA table_info(semantic_cache)")
                columns = [row["name"] for row in cursor.fetchall()]
                if "schema_hash" not in columns:
                    logger.info("Migrating database: adding schema_hash to semantic_cache")
                    conn.execute("ALTER TABLE semantic_cache ADD COLUMN schema_hash TEXT")
                
                # Check trajectories
                cursor = conn.execute("PRAGMA table_info(trajectories)")
                columns = [row["name"] for row in cursor.fetchall()]
                if "schema_hash" not in columns:
                    logger.info("Migrating database: adding schema_hash to trajectories")
                    conn.execute("ALTER TABLE trajectories ADD COLUMN schema_hash TEXT")
                
                # Create indexes
                conn.execute("CREATE INDEX IF NOT EXISTS idx_semantic_cache_schema ON semantic_cache(schema_hash)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_trajectories_schema ON trajectories(schema_hash)")
                
                conn.commit()
            logger.info("SQLite database initialized successfully", path=str(self.db_path))
        except Exception as e:
            logger.error("Failed to initialize SQLite database", error=str(e))

    # --- Vector Serialization ---
    def _serialize_vector(self, vec: np.ndarray) -> bytes:
        return vec.astype(np.float32).tobytes()

    def _deserialize_vector(self, blob: bytes) -> np.ndarray:
        return np.frombuffer(blob, dtype=np.float32)

    # --- Semantic Cache ---
    def get_cache_entries(self, active_columns: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        try:
            with self._get_connection() as conn:
                if active_columns is not None:
                    schema_hash = ",".join(sorted(active_columns))
                    rows = conn.execute(
                        "SELECT query, columns, code, embedding FROM semantic_cache WHERE schema_hash = ?",
                        (schema_hash,)
                    ).fetchall()
                else:
                    rows = conn.execute("SELECT query, columns, code, embedding FROM semantic_cache").fetchall()
                
                entries = []
                for row in rows:
                    entries.append({
                        "query": row["query"],
                        "columns": json.loads(row["columns"]),
                        "code": row["code"],
                        "embedding": self._deserialize_vector(row["embedding"])
                    })
                return entries
        except Exception as e:
            logger.error("Failed to fetch semantic cache from database", error=str(e))
            return []

    def save_cache_entry(self, query: str, columns: List[str], code: str, embedding: np.ndarray):
        try:
            schema_hash = ",".join(sorted(columns))
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO semantic_cache (query, schema_hash, columns, code, embedding) VALUES (?, ?, ?, ?, ?)",
                    (query.strip().lower(), schema_hash, json.dumps(columns), code, self._serialize_vector(embedding))
                )
                conn.commit()
        except Exception as e:
            logger.error("Failed to save semantic cache entry", error=str(e))

    # --- Trajectories (Failures Memory) ---
    def get_trajectory_entries(self, active_columns: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        try:
            with self._get_connection() as conn:
                if active_columns is not None:
                    schema_hash = ",".join(sorted(active_columns))
                    rows = conn.execute("""
                        SELECT instruction, columns, failed_code, error_message, corrected_code, embedding 
                        FROM trajectories WHERE schema_hash = ?
                    """, (schema_hash,)).fetchall()
                else:
                    rows = conn.execute("""
                        SELECT instruction, columns, failed_code, error_message, corrected_code, embedding 
                        FROM trajectories
                    """).fetchall()
                entries = []
                for row in rows:
                    entries.append({
                        "instruction": row["instruction"],
                        "columns": json.loads(row["columns"]),
                        "failed_code": row["failed_code"],
                        "error_message": row["error_message"],
                        "corrected_code": row["corrected_code"],
                        "embedding": self._deserialize_vector(row["embedding"])
                    })
                return entries
        except Exception as e:
            logger.error("Failed to fetch trajectories from database", error=str(e))
            return []

    def save_trajectory(self, instruction: str, columns: List[str], failed_code: str, error_message: str, corrected_code: str, embedding: np.ndarray):
        try:
            schema_hash = ",".join(sorted(columns))
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO trajectories (instruction, schema_hash, columns, failed_code, error_message, corrected_code, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    instruction.strip().lower(),
                    schema_hash,
                    json.dumps(columns),
                    failed_code,
                    error_message,
                    corrected_code,
                    self._serialize_vector(embedding)
                ))
                conn.commit()
        except Exception as e:
            logger.error("Failed to save trajectory memory", error=str(e))

    # --- Feedbacks ---
    def get_feedbacks(self) -> List[Dict[str, Any]]:
        try:
            with self._get_connection() as conn:
                rows = conn.execute("SELECT task, code, embedding FROM feedbacks").fetchall()
                entries = []
                for row in rows:
                    entries.append({
                        "task": row["task"],
                        "code": row["code"],
                        "embedding": self._deserialize_vector(row["embedding"]) if row["embedding"] else None
                    })
                return entries
        except Exception as e:
            logger.error("Failed to fetch feedbacks from database", error=str(e))
            return []

    def save_feedback(self, task: str, code: str, embedding: Optional[np.ndarray] = None):
        try:
            with self._get_connection() as conn:
                emb_blob = self._serialize_vector(embedding) if embedding is not None else None
                conn.execute(
                    "INSERT OR REPLACE INTO feedbacks (task, code, embedding) VALUES (?, ?, ?)",
                    (task.strip().lower(), code, emb_blob)
                )
                conn.commit()
        except Exception as e:
            logger.error("Failed to save feedback entry", error=str(e))

    # --- Working Memory ---
    def get_memories(self) -> List[Dict[str, Any]]:
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT timestamp, instruction, plan, code, result, meta FROM working_memory ORDER BY timestamp ASC"
                ).fetchall()
                entries = []
                for row in rows:
                    meta = {}
                    try:
                        meta = json.loads(row["meta"]) if row["meta"] else {}
                    except Exception:
                        pass
                    entries.append({
                        "timestamp": row["timestamp"],
                        "instruction": row["instruction"],
                        "plan": row["plan"],
                        "code": row["code"],
                        "result": row["result"],
                        "meta": meta
                    })
                return entries
        except Exception as e:
            logger.error("Failed to fetch working memory from database", error=str(e))
            return []

    def save_memory(self, timestamp: float, instruction: str, plan: str, code: str, result: str, meta: Dict[str, Any] = None):
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT INTO working_memory (timestamp, instruction, plan, code, result, meta) VALUES (?, ?, ?, ?, ?, ?)",
                    (timestamp, instruction, plan, code, result, json.dumps(meta or {}))
                )
                conn.commit()
        except Exception as e:
            logger.error("Failed to save working memory entry", error=str(e))

# Singleton instance
db_mgr = DatabaseManager()
