"""
Configuration File (config.py)

This file stores configuration variables and sensitive credentials for the application.
It is crucial for separating configuration from the main application logic.

NOTE: For production environments, it is highly recommended to use environment
variables to store sensitive data like API keys and passwords instead of
hardcoding them in the file. This enhances security and prevents accidental
exposure of credentials in version control.
"""
# Replace "YOUR_KIMI_API_KEY" with your actual key from Moonshot AI (Kimi)
import os
from dotenv import load_dotenv

# Load environment variables from a .env file if it exists.
# This is great for local development.
load_dotenv()

# --- Application Constants ---
AI_MODEL_NAME = "gemini-1.5-flash-latest"

# --- Secrets loaded from Environment ---
# os.getenv() will return None if the variable is not found.
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
# Load the AI model name from env, with a fallback to the current model
AI_MODEL_NAME = os.getenv("AI_MODEL_NAME", "gemini-1.5-flash-latest")

# --- Email Configuration ---
# Loaded from environment for sending newscasts and password resets.
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
DATABASE_URL = os.getenv("DATABASE_URL")

# --- Environment Configuration ---
FLASK_ENV = os.getenv("FLASK_ENV", "production")

# --- Validation ---
# Ensure that the required variables have been loaded.
if not GOOGLE_API_KEY:
    raise ValueError("A GOOGLE_API_KEY must be set in your environment variables or .env file.")
if not DATABASE_URL:
    if FLASK_ENV == "development":
        print("WARNING: DATABASE_URL not set. Falling back to local SQLite database 'newsapp.db'.")
        DATABASE_URL = "sqlite:///newsapp.db"
    else:
        raise ValueError("DATABASE_URL must be set in your environment variables or .env file for production.")
if not SENDER_EMAIL or not SENDER_PASSWORD:
    raise ValueError("SENDER_EMAIL and SENDER_PASSWORD must be set in your environment variables or .env file.")
if not FLASK_SECRET_KEY:
    raise ValueError("A FLASK_SECRET_KEY must be set in your environment variables or .env file.")