"""
Database Setup Script (database_setup.py)

This script initializes the database using the SQLAlchemy models.
It connects to the database specified by DATABASE_URL in the config
and creates all necessary tables if they don't already exist.
"""
import logging
import sys
import time
import os
from sqlalchemy import create_engine
from models import Base
from config import DATABASE_URL, FLASK_ENV

logger = logging.getLogger(__name__)

def setup_database():
    """
    Creates all tables defined in models.py in the configured database.
    This function is idempotent; it won't re-create tables that already exist.
    """
    max_retries = 5
    retry_delay = 5  # seconds

    for attempt in range(max_retries):
        try:
            logger.info(f"Initializing database in {FLASK_ENV} mode (attempt {attempt + 1}/{max_retries})...")
            engine = create_engine(DATABASE_URL)
            
            # Test the connection before proceeding
            with engine.connect() as connection:
                logger.info("Database connection successful.")
            
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables created or verified successfully.")
            return  # Exit the function on success
        except Exception as e:
            logger.warning(f"Database setup attempt {attempt + 1} failed: {e}")
            if attempt + 1 == max_retries:
                logger.critical("All database setup attempts failed. Exiting.")
                if "localhost" in str(e):
                    logger.critical("Error contains 'localhost'. Please ensure your DATABASE_URL environment variable is set correctly for your production environment.")
                sys.exit(1)  # Exit with an error code
            logger.info(f"Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)

if __name__ == "__main__":
    # Configure a basic logger for standalone execution
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    setup_database()