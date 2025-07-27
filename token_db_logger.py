import logging
from typing import Optional
from sqlalchemy.exc import SQLAlchemyError

from models import SessionLocal, ApiTokenUsage

logger = logging.getLogger(__name__)

# The initialize_database() function is no longer needed.
# The table will be created by the `database_setup.py` script.
def log_token_usage(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    user_id: Optional[str] = None,
    feature_name: Optional[str] = None
) -> None:
    """
    Logs a single API call's token usage to the database using SQLAlchemy.

    Args:
        model_name: The name of the model used (e.g., 'gemini-1.5-pro').
        prompt_tokens: Number of tokens in the prompt.
        completion_tokens: Number of tokens in the response.
        total_tokens: Total tokens used.
        user_id: The ID of the user making the request.
        feature_name: The application feature that made the API call.
    """
    db = SessionLocal()
    try:
        new_log = ApiTokenUsage(
            model_name=model_name,
            user_id=user_id,
            feature_name=feature_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens
        )
        db.add(new_log)
        db.commit()
    except SQLAlchemyError as e:
        logger.error(f"Database logging error for token usage: {e}")
        db.rollback()
    finally:
        db.close()