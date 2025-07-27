"""
One-Time Data Migration Script

This script migrates data from the old SQLite databases (newsapp.db and api_usage.db)
to the new PostgreSQL database configured in the .env file.

It performs the following actions:
1. Connects to the source SQLite databases.
2. Connects to the destination PostgreSQL database using SQLAlchemy.
3. Migrates users and their topic preferences from newsapp.db.
4. Migrates API errors from newsapp.db.
5. Migrates API token usage logs from api_usage.db.

This script is designed to be run once after the new database schema has been
created by `database_setup.py`. It includes checks to avoid duplicating data
if run more than once.
"""
import sqlite3
import logging
import sys
import os
from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

from models import Base, User, TopicPreference, ApiError, ApiTokenUsage

# --- Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()

NEWSAPP_DB = 'newsapp.db'
API_USAGE_DB = 'api_usage.db'

# --- Destination Database (PostgreSQL) ---
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL or not DATABASE_URL.startswith("postgresql"):
    raise ValueError("DATABASE_URL is not configured for PostgreSQL in your .env file.")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def migrate_users_and_preferences(dest_db):
    """Migrates users and their topic preferences from newsapp.db."""
    logging.info("Starting user and preferences migration...")
    if not os.path.exists(NEWSAPP_DB):
        logging.warning(f"{NEWSAPP_DB} not found. Skipping user migration.")
        return

    conn = sqlite3.connect(NEWSAPP_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()

    for user_data in users:
        # Check if user already exists in the destination
        if dest_db.query(User).filter_by(email=user_data['email']).first():
            logging.info(f"User {user_data['email']} already exists. Skipping.")
            continue

        new_user = User(
            id=user_data['id'],
            email=user_data['email'],
            password=user_data['password'],
            preferred_category=user_data['preferred_category'],
            preferred_region=user_data['preferred_region'],
            reset_token=user_data['reset_token'],
            reset_token_expiry=user_data['reset_token_expiry']
        )

        # Fetch and add topic preferences
        cursor.execute("SELECT topic_name FROM topic_preferences WHERE user_id = ?", (user_data['id'],))
        topics = cursor.fetchall()
        for topic_data in topics:
            new_topic = TopicPreference(topic_name=topic_data['topic_name'])
            new_user.topics.append(new_topic)

        dest_db.add(new_user)
        logging.info(f"Migrated user: {new_user.email}")

    conn.close()
    logging.info("User and preferences migration finished.")

def migrate_api_errors(dest_db):
    """Migrates API errors from newsapp.db."""
    logging.info("Starting API errors migration...")
    if not os.path.exists(NEWSAPP_DB):
        logging.warning(f"{NEWSAPP_DB} not found. Skipping API errors migration.")
        return

    conn = sqlite3.connect(NEWSAPP_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM api_errors")
    for error_data in cursor.fetchall():
        # Check if this exact error has been migrated to avoid duplicates.
        # This is a simple check, might not be perfect for all cases.
        if dest_db.query(ApiError).filter_by(
            error_message=error_data['error_message'],
            timestamp=error_data['timestamp']
        ).first():
            logging.info(f"Skipping duplicate API error from {error_data['timestamp']}.")
            continue

        new_error = ApiError(
            error_message=error_data['error_message'],
            timestamp=error_data['timestamp']
        )
        dest_db.add(new_error)
    conn.close()
    logging.info("API errors migration finished.")

def migrate_token_usage(dest_db):
    """Migrates token usage logs from api_usage.db."""
    logging.info("Starting token usage migration...")
    if not os.path.exists(API_USAGE_DB):
        logging.warning(f"{API_USAGE_DB} not found. Skipping token usage migration.")
        return

    conn = sqlite3.connect(API_USAGE_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM api_token_usage")
    for token_data in cursor.fetchall():
        # Check if this token usage log already exists to avoid duplicates.
        if dest_db.query(ApiTokenUsage).filter_by(request_id=token_data['request_id']).first():
            logging.info(f"Token usage for request_id {token_data['request_id']} already exists. Skipping.")
            continue

        # Explicitly map columns to be safer and to let the new DB handle the PK.
        new_log = ApiTokenUsage(
            request_id=token_data['request_id'],
            request_timestamp=token_data['request_timestamp'],
            model_name=token_data['model_name'],
            user_id=token_data['user_id'],
            feature_name=token_data['feature_name'],
            prompt_tokens=token_data['prompt_tokens'],
            completion_tokens=token_data['completion_tokens'],
            total_tokens=token_data['total_tokens']
        )
        dest_db.add(new_log)
    conn.close()
    logging.info("Token usage migration finished.")

if __name__ == "__main__":
    logging.info("--- Starting Data Migration to PostgreSQL ---")
    
    # Create the session within the main execution block
    dest_db = SessionLocal()
    try:
        migrate_users_and_preferences(dest_db)
        migrate_api_errors(dest_db)
        migrate_token_usage(dest_db)
        dest_db.commit()
        logging.info("Successfully committed all changes to the PostgreSQL database.")
    except Exception as e:
        logging.critical(f"A critical error occurred during migration: {e}")
        dest_db.rollback()
        sys.exit(1) # Exit with an error code on failure
    finally:
        dest_db.close()
    logging.info("--- Data Migration Complete ---")