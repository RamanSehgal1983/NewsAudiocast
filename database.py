"""
Database Session Management (database.py)

This module centralizes the database connection logic. It creates a single
SQLAlchemy engine and a SessionLocal class that can be used throughout the
application to interact with the database.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
