"""
Daily Newscast Generator (newscast_generator.py)

This is a standalone script designed to be run on a schedule (e.g., daily via a cron job).
Its primary purpose is to generate a personalized audio/video newscast for every
registered user and email it to them as an attachment.

The script performs the following steps for each user:
1. Fetches personalized news articles based on their preferences.
2. Uses the AI service to summarize the articles and create a news anchor script.
3. Converts the script to an audio file using Google Text-to-Speech (gTTS).
4. (Optional) Creates a simple video by combining the audio with a static background image using ffmpeg.
5. Sends an email to the user with the generated media file attached.
"""
import os
from gtts import gTTS
import datetime
import logging
import subprocess
from bs4 import BeautifulSoup
from ai_utils import summarize_texts_batch, rephrase_as_anchor, RateLimitException
from news_service import get_personalized_news
from utils import send_email
from token_db_logger import log_token_usage
from config import AI_MODEL_NAME
from models import SessionLocal, User
from sqlalchemy.exc import SQLAlchemyError

# --- Logging Setup ---
# Configure the logger to write to a file and the console
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# File Handler (writes to a file)
file_handler = logging.FileHandler('newscast_generator.log')
file_handler.setFormatter(log_formatter)

# Console Handler (writes to the console)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

# Get the root logger, set its level, and add the handlers
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

BACKGROUND_IMAGE_PATH = 'static/newscast_background.png'  # A default background image for the video

def create_video_from_audio(audio_path, image_path, output_path):
    """Creates a video file from an audio file and a static image using ffmpeg."""
    try:
        logging.info(f"Creating video with ffmpeg: {output_path}")
        if not os.path.exists(image_path):
            logging.warning(f"Background image not found at {image_path}. Skipping video creation.")
            return None

        command = [
            'ffmpeg',
            '-loop', '1',              # Loop the image
            '-i', image_path,         # Input image
            '-i', audio_path,         # Input audio
            '-c:v', 'libx264',        # Video codec
            '-tune', 'stillimage',    # Optimize for static image
            '-c:a', 'aac',            # Audio codec
            '-pix_fmt', 'yuv420p',    # Pixel format for compatibility
            '-shortest',              # Finish when the shortest stream (audio) ends
            '-y',                     # Overwrite output file without asking
            output_path
        ]

        # Run the command, capturing output and decoding it as text
        result = subprocess.run(command, capture_output=True, text=True)

        # Check if the command failed (non-zero exit code)
        if result.returncode != 0:
            logging.error(f"ffmpeg failed to create video file with exit code: {result.returncode}")
            # Log the actual error message from ffmpeg for easier debugging
            logging.error(f"FFmpeg stderr:\n{result.stderr}")
            return None

        logging.info("Video created successfully.")
        return output_path
    except FileNotFoundError:
        logging.error("ffmpeg is not installed or not in your system's PATH. Please install ffmpeg to create videos.")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred during video creation: {e}")
        return None

def get_all_users():
    """Fetches all users from the database using SQLAlchemy."""
    db = SessionLocal()
    try:
        # Query for id and email of all users. This returns a list of tuples.
        users = db.query(User.id, User.email).all()
        return users
    except SQLAlchemyError as e:
        logging.critical(f"Database error when fetching users: {e}")
        return []
    finally:
        db.close()

def generate_newscast_content(user_id):
    """Fetches news, summarizes it, and generates a script."""
    combined_entries = get_personalized_news(user_id)
    if not combined_entries:
        return None

    logging.info(f"Fetched {len(combined_entries)} articles. Summarizing in a single batch call...")
    
    texts_to_summarize = []
    for entry in combined_entries:
        if hasattr(entry, 'summary'):
            plain_text = BeautifulSoup(entry.summary, "html.parser").get_text()
            texts_to_summarize.append(plain_text[:3000])

    if not texts_to_summarize:
        logging.warning("No article content found to summarize.")
        return None

    try:
        summaries, usage_data_summarize = summarize_texts_batch(texts_to_summarize)
        if usage_data_summarize:
            log_token_usage(
                model_name=AI_MODEL_NAME,
                prompt_tokens=usage_data_summarize.get('prompt_tokens', 0),
                completion_tokens=usage_data_summarize.get('completion_tokens', 0),
                total_tokens=usage_data_summarize.get('total_tokens', 0),
                user_id=str(user_id),
                feature_name="newscast-summarization"
            )
    except RateLimitException:
        logger.error(f"AI rate limit hit during summarization for user {user_id}. Skipping.")
        return None

    if not summaries:
        # This will be true if the batch call returns None (fatal error) or an empty list
        logging.error(f"Stopping content generation for user {user_id} due to a failure in batch summarization.")
        return None

    logging.info("Generating anchor script...")
    try:
        anchor_script, usage_data_rephrase = rephrase_as_anchor(" ".join(summaries))
        if usage_data_rephrase:
            log_token_usage(
                model_name=AI_MODEL_NAME,
                prompt_tokens=usage_data_rephrase.get('prompt_tokens', 0),
                completion_tokens=usage_data_rephrase.get('completion_tokens', 0),
                total_tokens=usage_data_rephrase.get('total_tokens', 0),
                user_id=str(user_id),
                feature_name="newscast-rephrasing"
            )
    except RateLimitException:
        logger.error(f"AI rate limit hit during rephrasing for user {user_id}. Skipping.")
        return None

    return anchor_script

def create_media_files(anchor_script, user_id, output_folder):
    """Creates audio and video files from the anchor script."""
    date_str = datetime.date.today().isoformat()
    audio_filename = f"audiocast_{user_id}_{date_str}.mp3"
    audio_filepath = os.path.join(output_folder, audio_filename)

    logging.info(f"Generating audio file: {audio_filepath}")
    try:
        tts = gTTS(text=anchor_script, lang='en')
        tts.save(audio_filepath)
        logging.info("Audio file saved successfully.")
    except Exception as e:
        logging.error(f"Failed to create audio file: {e}")
        return None, None

    video_filename = f"newscast_{user_id}_{date_str}.mp4"
    video_filepath = os.path.join(output_folder, video_filename)
    created_video_path = create_video_from_audio(audio_filepath, BACKGROUND_IMAGE_PATH, video_filepath)
    
    return audio_filepath, created_video_path

def process_user(user_id, user_email):
    """
    Processes a single user: generates content, creates media, and sends email.
    """
    logging.info(f"--- Processing user: {user_email} (ID: {user_id}) ---")

    # 1. Generate the newscast script
    anchor_script = generate_newscast_content(user_id)
    if not anchor_script:
        logging.warning(f"Could not generate newscast content for {user_email}. Skipping.")
        return

    # 2. Create the output directory relative to the script's location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_folder = os.path.join(script_dir, 'Daily Newscast')
    os.makedirs(output_folder, exist_ok=True)

    # 3. Create the audio and video files
    audio_filepath, video_filepath = create_media_files(anchor_script, user_id, output_folder)
    if not audio_filepath:
        logging.warning(f"Failed to create media files for {user_email}. Skipping.")
        return

    # 4. Send the email with the correct attachment (video if created, otherwise audio)
    if video_filepath and os.path.exists(video_filepath):
        logging.info(f"Preparing to send video newscast to {user_email}...")
        email_subject = "Your Daily Video Newscast"
        email_body = "Good morning! Here is your personalized video newscast for today."
        send_email(user_email, email_subject, email_body, video_filepath)
    else:
        logging.warning(f"Video creation failed. Sending audio-only newscast to {user_email}...")
        email_subject = "Your Daily News Audiocast"
        email_body = "Good morning! Here is your personalized news audiocast for today."
        send_email(user_email, email_subject, email_body, audio_filepath)

def main():
    """Main function to generate and email the audiocast."""
    logging.info("="*50)
    logging.info("Starting daily newscast generation process...")

    all_users = get_all_users()
    if not all_users:
        logging.warning("No users found in the database or database error occurred. Exiting.")
        return

    logging.info(f"Found {len(all_users)} users. Starting newscast generation for each.")

    # Loop through each user to generate and send their personalized newscast
    for user_id, user_email in all_users:
        process_user(user_id, user_email)
    
    logging.info("Script finished.")
    logging.info("="*50 + "\n")

if __name__ == "__main__":
    main()