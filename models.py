"""
Database Models (models.py)

This file defines the database schema using SQLAlchemy's ORM. Each class
represents a table in the database. This approach provides a more robust and
maintainable way to interact with the database compared to raw SQL queries.
"""
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, TIMESTAMP
import uuid
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    preferred_category = Column(String)
    preferred_region = Column(String)
    reset_token = Column(String)
    reset_token_expiry = Column(TIMESTAMP)
    
    # Relationship to topic preferences
    topics = relationship("TopicPreference", back_populates="user", cascade="all, delete-orphan")

class TopicPreference(Base):
    __tablename__ = 'topic_preferences'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    topic_name = Column(String, nullable=False)

    # Relationship back to the user
    user = relationship("User", back_populates="topics")

class ApiError(Base):
    __tablename__ = 'api_errors'
    id = Column(Integer, primary_key=True)
    error_message = Column(String, nullable=False)
    timestamp = Column(TIMESTAMP, nullable=False, server_default=func.now())

class ApiTokenUsage(Base):
    __tablename__ = 'api_token_usage'
    id = Column(Integer, primary_key=True)
    # The original code generates a UUID string, so String is appropriate.
    request_id = Column(String, unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    request_timestamp = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    model_name = Column(String, nullable=False)
    user_id = Column(String, nullable=True)
    feature_name = Column(String, nullable=True)
    prompt_tokens = Column(Integer, nullable=False)
    completion_tokens = Column(Integer, nullable=False)
    total_tokens = Column(Integer, nullable=False)
