"""
AI Utilities for Google Gemini (ai_utils.py)

This module centralizes all interactions with the AI model via the Google Gemini API.
It is responsible for:
- Calling the Google Gemini API.
- Providing functions to perform specific AI tasks, such as:
  - `summarize_text`: Summarizes a single piece of text.
  - `rephrase_as_anchor`: Rewrites text into a news anchor script.
  - `summarize_texts_batch`: Efficiently summarizes multiple texts.
- Handling API-specific errors (e.g., rate limits) and providing fallbacks.
"""
import logging
import re
from datetime import datetime, timedelta
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from sqlalchemy.exc import SQLAlchemyError
from config import GOOGLE_API_KEY, AI_MODEL_NAME
from models import SessionLocal, ApiError

logger = logging.getLogger(__name__)

# --- Google Gemini API Configuration ---
class RateLimitException(Exception):
    """Custom exception for API rate limit errors."""
    pass


try:
    genai.configure(api_key=GOOGLE_API_KEY)
except Exception as e:
    logger.critical(f"Failed to configure Google AI. Please check your GOOGLE_API_KEY. Error: {e}")

def _log_rate_limit_error_if_needed():
    """
    Logs a rate limit error to the database if one hasn't been logged recently.
    This prevents spamming the log for every request after the limit is hit.
    """
    db = SessionLocal()
    try:
        # Check for the most recent rate limit error using SQLAlchemy
        last_error = db.query(ApiError).order_by(ApiError.timestamp.desc()).first()

        # The timestamp from SQLAlchemy is a datetime object, no need for fromisoformat
        # Only log if no error exists or the last one was more than 23 hours ago
        if not last_error or (datetime.now() - last_error.timestamp) > timedelta(hours=23):
            logger.info("Logging new API rate limit error to the database.")
            new_error = ApiError(error_message="Google Gemini API rate limit exceeded.")
            db.add(new_error)
            db.commit()
    except SQLAlchemyError as e:
        logger.error(f"Database error while trying to log API rate limit: {e}")
        db.rollback()
    finally:
        db.close()

def _call_google_api(prompt: str, temperature: float):
    """
    Helper function to call the Google Gemini API and handle responses.
    Returns the full response object, or None on failure.
    Raises RateLimitException if the API quota is exceeded.
    """
    try:
        model = genai.GenerativeModel(AI_MODEL_NAME)
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=temperature)
        )
        return response
    except ResourceExhausted as e:
        logger.error(f"Google Gemini API rate limit exceeded: {e}")
        _log_rate_limit_error_if_needed()
        raise RateLimitException("AI rate limit exceeded.") from e
    except Exception as e:
        logger.error(f"An error occurred calling Google Gemini API: {e}")
        return None

def summarize_text(text: str) -> tuple[str, dict | None]:
    """
    Summarizes a given piece of text using Google Gemini.
    Returns a tuple of (summary, usage_metadata) or (fallback_text, None) on failure.
    """
    prompt = f"You are an expert news summarizer. Summarize the following text concisely in no more than 100 words:\n\n{text}"
    response = _call_google_api(prompt, temperature=0.3)
    if response:
        usage_metadata = {
            'prompt_tokens': response.usage_metadata.prompt_token_count,
            'completion_tokens': response.usage_metadata.candidates_token_count,
            'total_tokens': response.usage_metadata.total_token_count,
        }
        return response.text, usage_metadata
    else:
        logger.warning("Falling back to simple text truncation for summarization.")
        fallback_summary = (text[:150] + '...') if len(text) > 150 else text
        return fallback_summary, None

def rephrase_as_anchor(text: str) -> tuple[str, dict | None]:
    """
    Uses Google Gemini to rewrite text into a news anchor script.
    Returns a tuple of (script, usage_metadata) or (fallback_text, None) on failure.
    """
    prompt = f"You are a professional news anchor. Rewrite the following text into a cohesive, flowing news script that you would read on air. Make it engaging and professional:\n\n{text}"
    response = _call_google_api(prompt, temperature=0.7)
    if response:
        usage_metadata = {
            'prompt_tokens': response.usage_metadata.prompt_token_count,
            'completion_tokens': response.usage_metadata.candidates_token_count,
            'total_tokens': response.usage_metadata.total_token_count,
        }
        return response.text, usage_metadata
    else:
        logger.warning("Falling back to a default message for anchor rephrasing.")
        return "Could not generate the news anchor script at this time.", None

def summarize_texts_batch(texts: list[str]) -> tuple[list[str], dict | None]:
    """
    Summarizes a batch of texts in a single API call to Google Gemini.
    Returns a tuple containing a list of summaries and usage metadata,
    or a list of truncated texts and None on failure.
    """
    if not texts:
        return [], None

    # Construct a single prompt with instructions for batch processing
    prompt_parts = [
        "You are an expert news summarizer. I will provide a list of articles. For each article, provide a concise and clear summary of no more than 100 words.",
        "Present the output as a numbered list. Each summary must start with 'SUMMARY <number>:' on a new line, where <number> is the article number.",
        "For example:\nSUMMARY 1:\n<summary for article 1>\n\nSUMMARY 2:\n<summary for article 2>",
        "\nHere are the articles:\n"
    ]
    for i, text in enumerate(texts, 1):
        prompt_parts.append(f"ARTICLE {i}:\n{text}\n")

    full_prompt = "\n".join(prompt_parts)
    response = _call_google_api(full_prompt, temperature=0.3)

    if not response:
        logger.error("Batch summarization failed. Falling back to truncating each article.")
        fallback_summaries = [(text[:150] + '...') if len(text) > 150 else text for text in texts]
        return fallback_summaries, None

    try:
        usage_metadata = {
            'prompt_tokens': response.usage_metadata.prompt_token_count,
            'completion_tokens': response.usage_metadata.candidates_token_count,
            'total_tokens': response.usage_metadata.total_token_count,
        }

        # Split the response text into individual summaries using regex
        summaries = re.split(r"SUMMARY\s*\d+:", response.text.strip(), flags=re.IGNORECASE)[1:]
        cleaned_summaries = [s.strip() for s in summaries]

        if len(cleaned_summaries) == len(texts):
            return cleaned_summaries, usage_metadata
        raise ValueError(f"Expected {len(texts)} summaries, but parsed {len(cleaned_summaries)}.")
    except Exception as e:
        logger.error(f"An error occurred parsing the batch summary response: {e}. Falling back to truncation.")
        fallback_summaries = [(text[:150] + '...') if len(text) > 150 else text for text in texts]
        return fallback_summaries, None