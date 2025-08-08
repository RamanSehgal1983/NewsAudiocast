"""
Main Flask Application File (app.py)

This script serves as the central entry point for the web application. It handles all
web-based interactions, including:
- Routing for different pages (home, login, register, preferences).
- User session management (login, logout, authentication).
- Fetching personalized news content using the news_service.
- Interacting with AI utilities (ai_utils) to summarize and rephrase news.
- Rendering HTML templates to display content to the user.
"""
# Import all the necessary libraries and modules from Flask and other packages
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, g, send_from_directory
import requests  # For making HTTP requests to external APIs (like the IP location API)
from gtts import gTTS  # For converting text to speech (Google Text-to-Speech)
import os  # For interacting with the operating system (e.g., creating directories, checking file paths)
import hashlib  # For creating a unique hash of the audio script to use as a filename
from itsdangerous import URLSafeTimedSerializer  # For generating secure, timed tokens (used for password resets)
from datetime import datetime, timedelta  # For handling dates and times (used for token expiry)
from sqlalchemy.orm import Session, joinedload  # For interacting with the database
from token_db_logger import log_token_usage  # A custom function to log AI model token usage
from werkzeug.security import generate_password_hash, check_password_hash  # For securely hashing and checking passwords
from bs4 import BeautifulSoup  # For parsing HTML content from the news feeds

# Import custom modules and variables from within the project
from constants import NEWS_FEEDS, REGIONS  # Predefined lists of news categories and countries
from ai_utils import summarize_texts_batch, rephrase_as_anchor, RateLimitException  # AI helper functions
from news_service import get_personalized_news  # Service for fetching news
from utils import send_email  # Utility for sending emails (for password resets)
from config import FLASK_SECRET_KEY, AI_MODEL_NAME, DATABASE_URL, PERSISTENT_STORAGE_PATH  # Configuration variables
from models import User, TopicPreference, ApiError  # Database models
from database import SessionLocal  # Database session factory
from extensions import cache  # Caching extension

# Create the main Flask application instance
app = Flask(__name__)
# Set a secret key for the application, which is used to keep client-side sessions secure.
app.secret_key = FLASK_SECRET_KEY
# Store the path for persistent storage (like generated audio files) in the app's configuration.
app.config['PERSISTENT_STORAGE_PATH'] = PERSISTENT_STORAGE_PATH

# Initialize the caching extension with the Flask app.
cache.init_app(app)

# This function takes an IP address and returns the country code and country name.
def get_location_from_ip(ip_address):
    """Gets country code and name from an IP address using a free geolocation API."""
    # If the IP is 127.0.0.1 (localhost), it means we are testing locally.
    # So, we return default values ('US', 'the United States').
    if ip_address == '127.0.0.1':
        return 'US', 'the United States'

    try:
        # Make a request to a free IP geolocation API.
        response = requests.get(f'http://ip-api.com/json/{ip_address}?fields=status,country,countryCode')
        response.raise_for_status()  # Raise an error if the request failed
        data = response.json()
        # If the API call was successful, return the country code and name.
        if data.get('status') == 'success':
            return data.get('countryCode'), data.get('country')
    except requests.exceptions.RequestException as e:
        # If there was an error, log it for debugging purposes.
        app.logger.error(f"Could not get location for IP {ip_address}: {e}")
    
    # If the API fails or the IP is private, return default values.
    return None, 'Worldwide'

# This function runs before each request to the application.
@app.before_request
def before_request():
    # It opens a new database session and stores it in the 'g' object.
    # The 'g' object is a special object in Flask that is unique for each request.
    g.db = SessionLocal()

# This function runs after each request.
@app.after_request
def after_request(response):
    # It closes the database session to ensure that the connection is returned to the pool.
    g.db.close()
    return response

# This is the main route for the home page.
@app.route('/')
def display_news():
    # Check if a user is logged in by looking for their email in the session.
    user_email = session.get('email')
    user = None
    user_id = None

    # If the user is logged in, get their details from the database.
    if user_email:
        user = g.db.query(User).options(joinedload(User.topics)).filter_by(email=user_email).first()
        if user:
            user_id = user.id

    # Get the user's IP address. It checks for 'X-Forwarded-For' header in case the app is behind a proxy.
    if request.headers.getlist("X-Forwarded-For"):
       ip_addr = request.headers.getlist("X-Forwarded-For")[0].split(',')[0].strip()
    else:
       ip_addr = request.remote_addr

    # Get the user's location based on their IP address.
    country_code, country_name = get_location_from_ip(ip_addr)

    # Check if the user has submitted a search query in the URL (e.g., /?q=AI).
    search_query = request.args.get('q', None)
    category = request.args.get('category', None)

    # Call the news service to get the news. This one function handles all cases:
    # - Logged-in user with preferences
    # - Anonymous user
    # - User performing a search
    entries_with_logos = get_personalized_news(
        db=g.db, user_id=user_id, search_query=search_query, country_code=country_code, category=category
    )

    # Prepare to collect the text from the news articles for summarization.
    texts_to_summarize = []
    entries_with_summary = []
    for entry, logo_url in entries_with_logos:
        # Remove the source from the title, e.g., "Title - Source" -> "Title"
        if hasattr(entry, 'title') and hasattr(entry, 'source') and entry.source.title:
            # Check if the title ends with the source title and remove it
            if entry.title.endswith(f" - {entry.source.title}"):
                entry.title = entry.title.rsplit(f" - {entry.source.title}", 1)[0].strip()
            # Fallback for cases where the source title might be slightly different or not present
            elif " - " in entry.title:
                entry.title = entry.title.rsplit(' - ', 1)[0].strip()

        # Only process articles that have a summary.
        if hasattr(entry, 'summary'):
            # Use BeautifulSoup to remove any HTML tags from the summary.
            soup = BeautifulSoup(entry.summary, "html.parser")
            plain_text = soup.get_text()
            # Add the first 3000 characters of the text to the list to be summarized.
            texts_to_summarize.append(plain_text[:3000])
            entries_with_summary.append(entry)

    try:
        # Summarize all the collected article texts in a single batch call to the AI for efficiency.
        batch_summaries, usage_data = summarize_texts_batch(texts_to_summarize) if texts_to_summarize else ([], None)
    except RateLimitException:
        # If the AI API rate limit is hit, show a specific error page.
        last_error_time = "an unknown time"
        last_error = g.db.query(ApiError).order_by(ApiError.timestamp.desc()).first()
        if last_error:
            error_dt = last_error.timestamp
            last_error_time = error_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
        else:
            app.logger.warning("Could not fetch last API error time from DB because no errors were found.")
        return render_template('rate_limit.html', last_error_time=last_error_time), 503

    # If the summarization was successful, log how many tokens were used.
    if usage_data:
        log_token_usage(
            db=g.db,
            model_name=AI_MODEL_NAME,
            prompt_tokens=usage_data.get('prompt_tokens', 0),
            completion_tokens=usage_data.get('completion_tokens', 0),
            total_tokens=usage_data.get('total_tokens', 0),
            user_id=str(user_id) if user_id else "anonymous",
            feature_name="batch-summarization"
        )

    # Map the generated summaries back to their original articles.
    summary_map = {}
    if batch_summaries and len(batch_summaries) == len(entries_with_summary):
        for i, entry in enumerate(entries_with_summary):
            summary_map[entry.link] = batch_summaries[i]

    # Create the final list of summaries in the correct order.
    summaries = [summary_map.get(entry.link, "No summary available for this article.") for entry, logo_url in entries_with_logos]

    # If there are summaries, join them together and store them in the session.
    # This is so the '/generate_audio' route can access them.
    if summaries:
        session['combined_summaries'] = " ".join(summaries)
    else:
        # If there are no summaries, remove the old ones from the session.
        session.pop('combined_summaries', None)

    # Render the main 'index.html' page and pass all the necessary data to it.
    return render_template(
        'index.html',
        entries_with_logos=entries_with_logos,
        summaries=summaries,
        user=user,
        search_query=search_query,
        region_name=country_name,
        category=category
    )


# This route handles the generation of the audio newscast.
@app.route('/generate_audio')
def generate_audio():
    """Generates the news anchor script and audio file on-demand."""
    # Get the combined summaries from the session.
    combined_summaries = session.get('combined_summaries')
    if not combined_summaries:
        return jsonify({'error': 'No summaries available to generate audio.'}), 404

    try:
        # Use the AI to rephrase the summaries into a news anchor script.
        anchor_script, usage_data = rephrase_as_anchor(combined_summaries)
        if not anchor_script or not anchor_script.strip():
            app.logger.error("AI service returned an empty anchor script.")
            return jsonify({'error': 'Failed to generate a valid news script from the AI service.'}), 500
    except RateLimitException:
        return jsonify({'error': 'AI limit exceeded by the website server, please try again in 24 hours'}), 503

    # Log the token usage for the rephrasing AI call.
    if usage_data:
        user_id = None
        user_email = session.get('email')
        if user_email:
            user = g.db.query(User).filter_by(email=user_email).first()
            if user:
                user_id = user.id
        log_token_usage(
            db=g.db,
            model_name=AI_MODEL_NAME,
            prompt_tokens=usage_data.get('prompt_tokens', 0),
            completion_tokens=usage_data.get('completion_tokens', 0),
            total_tokens=usage_data.get('total_tokens', 0),
            user_id=str(user_id) if user_id else "anonymous",
            feature_name="anchor-script-rephrasing"
        )

    # Create a unique filename for the audio file by hashing the script content.
    # This ensures that if the same script is generated again, we can reuse the existing audio file.
    filename_hash = hashlib.md5(anchor_script.encode()).hexdigest()
    audio_filename = f"{filename_hash}.mp3"

    # Define the path where the audio file will be saved.
    storage_path = app.config['PERSISTENT_STORAGE_PATH']
    os.makedirs(storage_path, exist_ok=True)  # Create the directory if it doesn't exist
    audio_filepath = os.path.join(storage_path, audio_filename)

    # If the audio file doesn't already exist, create it.
    if not os.path.exists(audio_filepath):
        try:
            app.logger.info(f"Generating new audio file: {audio_filepath}")
            # Use Google Text-to-Speech (gTTS) to convert the script to an MP3 file.
            tts = gTTS(text=anchor_script, lang='en')
            tts.save(audio_filepath)
            app.logger.info("Audio file saved successfully.")
        except Exception as e:
            app.logger.error(f"Failed to generate or save audio file with gTTS: {e}")
            return jsonify({'error': 'The server encountered an error while creating the audio file.'}), 500

    # Return the URL of the generated audio file to the frontend.
    return jsonify({'audio_file': url_for('serve_media', filename=audio_filename)})

# This route serves the generated media files (the audio).
@app.route('/media/<path:filename>')
def serve_media(filename):
    """Serves files from the persistent storage directory."""
    storage_path = app.config.get('PERSISTENT_STORAGE_PATH')
    if not storage_path or not os.path.isdir(storage_path):
        return "Media storage not configured or not found on the server.", 500
    # send_from_directory is a secure way to send files from a directory.
    return send_from_directory(storage_path, filename)

# This route handles user registration.
@app.route('/register', methods=['GET', 'POST'])
def register():
    # If the user is already logged in, redirect them to the home page.
    if 'email' in session:
        flash('You are already logged in.', 'info')
        return redirect(url_for('display_news'))

    # If the form is submitted (POST request)
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        # Hash the password for security before storing it.
        hashed_password = generate_password_hash(password)

        try:
            # Check if a user with this email already exists.
            existing_user = g.db.query(User).filter_by(email=email).first()
            if existing_user:
                flash('An account with this email already exists.', 'danger')
                return redirect(url_for('register'))

            # Create a new user and add them to the database.
            new_user = User(email=email, password=hashed_password)
            g.db.add(new_user)
            g.db.commit()

            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            app.logger.critical(f"Database error during registration for '{email}': {e}")
            flash('An error occurred during registration. Please try again later.', 'danger')
            return render_template('register.html', user=None), 500

    # If it's a GET request, just show the registration page.
    return render_template('register.html', user=None)

# This route handles user login.
@app.route('/login', methods=['GET', 'POST'])
def login():
    # If user is already logged in, redirect them.
    if 'email' in session:
        return redirect(url_for('loading'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        # Find the user in the database.
        user = g.db.query(User).filter_by(email=email).first()

        # Check if the user exists and the password is correct.
        if user and check_password_hash(user.password, password):
            # If correct, store their email in the session to log them in.
            session['email'] = user.email
            app.logger.info(f"User '{email}' logged in successfully.")
            return redirect(url_for('display_news'))
        else:
            flash('Invalid email or password.', 'danger')
            app.logger.warning(f"Failed login attempt for email: '{email}'")

    return render_template('login.html', user=None)

# This route handles user logout.
@app.route('/logout')
def logout():
    # Remove the user's email from the session.
    session.pop('email', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# This route handles the 'forgot password' functionality.
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        user = g.db.query(User).filter_by(email=email).first()

        if user:
            # If the user exists, generate a secure, timed token.
            s = URLSafeTimedSerializer(app.secret_key)
            token = s.dumps(email, salt='password-reset-salt')
            
            # Save the token and its expiry time to the user's record in the database.
            user.reset_token = token
            user.reset_token_expiry = datetime.now() + timedelta(hours=1)
            g.db.commit()
            
            # Create the password reset link and send it to the user's email.
            reset_url = url_for('reset_password', token=token, _external=True)
            subject = "Password Reset Request"
            body = f"""To reset your password, visit the following link:
{reset_url}

If you did not make this request then simply ignore this email and no changes will be made.
This link will expire in 1 hour.
"""
            send_email(email, subject, body)
        
        # Show a generic message whether the user was found or not.
        # This prevents attackers from checking which emails are registered.
        flash('If that email address is in our database, a password reset link has been sent.', 'info')
        return redirect(url_for('login'))

    return render_template('forgot_password.html')

# This route handles the actual password reset after the user clicks the link in their email.
@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    s = URLSafeTimedSerializer(app.secret_key)
    try:
        # Try to load the email from the token. It will fail if the token is invalid or expired (max_age=3600 seconds).
        email = s.loads(token, salt='password-reset-salt', max_age=3600)
    except Exception:
        flash('The password reset link is invalid or has expired.', 'danger')
        return redirect(url_for('login'))

    # Find the user associated with the token.
    user = g.db.query(User).filter(
        User.email == email,
        User.reset_token == token,
        User.reset_token_expiry > datetime.now()
    ).first()

    if not user:
        flash('The password reset link is invalid or has expired.', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', token=token)

        # Hash the new password and update it in the database.
        hashed_password = generate_password_hash(password)

        user.password = hashed_password
        # Clear the reset token so it can't be used again.
        user.reset_token = None
        user.reset_token_expiry = None
        g.db.commit()
        app.logger.info(f"Password reset successfully for user {email}")

        flash('Your password has been successfully reset. Please log in.', 'success')
        return redirect(url_for('login'))
    
    # If it's a GET request, show the password reset form.
    return render_template('reset_password.html', token=token)

# This route allows logged-in users to manage their preferences.
@app.route('/preferences', methods=['GET', 'POST'])
def preferences():
    if 'email' not in session:
        flash('You must be logged in to view this page.', 'warning')
        return redirect(url_for('login'))

    email = session['email']
    user = g.db.query(User).options(joinedload(User.topics)).filter_by(email=email).first()

    if not user:
        session.pop('email', None)
        flash('User not found. Please log in again.', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Update the user's preferred category and region from the form.
        user.preferred_category = request.form['category']
        user.preferred_region = request.form.get('region')

        # To update the followed topics, it's easiest to delete the old ones and add the new ones.
        g.db.query(TopicPreference).filter_by(user_id=user.id).delete()

        # Get the new topics from the form and add them to the database.
        new_topics = [request.form[f'topic{i}'] for i in range(1, 6) if request.form.get(f'topic{i}')]
        for topic_name in new_topics:
            topic_pref = TopicPreference(user_id=user.id, topic_name=topic_name)
            g.db.add(topic_pref)

        g.db.commit()
        flash('Your preferences have been saved!', 'success')
        return redirect(url_for('preferences'))

    # For a GET request, fetch the user's current preferences to display them on the page.
    followed_topics = [topic.topic_name for topic in user.topics]

    return render_template('preferences.html',
                           news_feeds=NEWS_FEEDS,
                           regions=REGIONS,
                           user=user,
                           followed_topics=followed_topics)

# This block runs the application when the script is executed directly.
if __name__ == '__main__':
    with app.app_context():
        # The 'debug=True' argument enables debug mode, which provides helpful error pages
        # and automatically reloads the server when code changes.
        app.run(debug=True)
