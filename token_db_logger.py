import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

# --- Database Configuration ---
DB_FILE = "api_usage.db"


def get_db_connection():
    """Establishes and returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database():
    """
    Creates the `api_token_usage` table if it doesn't already exist.
    This function should be called once when your application starts up.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # SQL command adapted for SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT UNIQUE NOT NULL,
                request_timestamp TEXT NOT NULL,
                model_name TEXT NOT NULL,
                user_id TEXT,
                feature_name TEXT,
                prompt_tokens INTEGER NOT NULL,
                completion_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL
            );
        """)
        conn.commit()
        print("Database initialized successfully.")
    except sqlite3.Error as e:
        print(f"Database initialization error: {e}")
    finally:
        if conn:
            conn.close()


def log_token_usage(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    user_id: Optional[str] = None,
    feature_name: Optional[str] = None
) -> Optional[str]:
    """
    Logs a single API call's token usage to the SQLite database.

    Args:
        model_name: The name of the model used (e.g., 'gemini-1.5-pro').
        prompt_tokens: Number of tokens in the prompt.
        completion_tokens: Number of tokens in the response.
        total_tokens: Total tokens used.
        user_id: The ID of the user or service making the request.
        feature_name: The application feature that made the request.

    Returns:
        The unique request_id for the logged entry, or None if logging failed.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    request_id = str(uuid.uuid4())
    # Use ISO 8601 format for timestamps, which is standard for SQLite
    request_timestamp = datetime.now(timezone.utc).isoformat()

    try:
        cursor.execute(
            """
            INSERT INTO api_token_usage (
                request_id, request_timestamp, model_name, user_id,
                feature_name, prompt_tokens, completion_tokens, total_tokens
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (request_id, request_timestamp, model_name, user_id, feature_name,
             prompt_tokens, completion_tokens, total_tokens)
        )
        conn.commit()
        return request_id
    except sqlite3.Error as e:
        print(f"Database logging error: {e}")
        return None
    finally:
        conn.close()