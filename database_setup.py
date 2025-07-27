"""
Database Setup Script (database_setup.py)

This script is responsible for initializing the SQLite database (`newsapp.db`).
It creates the necessary tables ('users', 'topic_preferences') and adds the
required columns if they do not already exist.

The script is designed to be idempotent, meaning it can be run multiple times
without causing errors or duplicating schema elements. This makes it safe to
run for both initial setup and for applying schema updates to an existing database.
"""
import sqlite3
import logging

logger = logging.getLogger(__name__)

def add_column_if_not_exists(cursor, table_name, column_name, column_type):
    """
    Checks if a column exists in a table and adds it if it doesn't.
    This prevents errors when running the script on an already-migrated database.
    """
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [info[1] for info in cursor.fetchall()]
    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        logger.info(f"Column '{column_name}' added to table '{table_name}'.")
    else:
        logger.info(f"Column '{column_name}' already exists in table '{table_name}'.")

def setup_database():
    """
    Connects to the database and ensures all necessary tables and columns exist.
    This script is idempotent and can be run safely multiple times to create or
    update the database schema without causing errors.
    """
    conn = None
    try:
        conn = sqlite3.connect('newsapp.db')
        cursor = conn.cursor()

        # 1. Create the 'users' table if it doesn't exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        );
        """)
        logger.info("Table 'users' created or verified.")

        # 2. Add columns to 'users' table if they don't exist
        add_column_if_not_exists(cursor, 'users', 'preferred_category', 'TEXT')
        add_column_if_not_exists(cursor, 'users', 'preferred_region', 'TEXT')
        add_column_if_not_exists(cursor, 'users', 'reset_token', 'TEXT')
        add_column_if_not_exists(cursor, 'users', 'reset_token_expiry', 'TIMESTAMP')

        # 3. Create the 'topic_preferences' table if it doesn't exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS topic_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic_name TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );
        """)
        logger.info("Table 'topic_preferences' created or verified.")

        # 4. Create the 'api_errors' table if it doesn't exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_message TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)
        logger.info("Table 'api_errors' created or verified.")

        conn.commit()
        logger.info("Database setup/verification complete.")

    except sqlite3.Error as e:
        logger.error(f"An error occurred during database setup: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    # Configure a basic logger for standalone execution
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    setup_database()