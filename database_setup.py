"""
Database Setup Script (database_setup.py)

This script initializes the database using the SQLAlchemy models.
It connects to the database specified by DATABASE_URL in the config
and creates all necessary tables if they don't already exist.
"""
import logging
from models import Base, engine

logger = logging.getLogger(__name__)

def setup_database():
    """
    Creates all tables defined in models.py in the configured database.
    This function is idempotent; it won't re-create tables that already exist.
    """
    try:
        logger.info("Initializing database and creating tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created or verified successfully.")
    except Exception as e:
        logger.critical(f"An error occurred during database setup: {e}")

if __name__ == "__main__":
    # Configure a basic logger for standalone execution
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    setup_database()