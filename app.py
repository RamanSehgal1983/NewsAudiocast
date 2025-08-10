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
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, g, send_from_directory
import requests
from gtts import gTTS
import os
import hashlib
from itsdangerous import URLSafeTimedSerializer
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from token_db_logger import log_token_usage
from werkzeug.security import generate_password_hash, check_password_hash
from bs4 import BeautifulSoup
from constants import NEWS_FEEDS, REGIONS
from ai_utils import summarize_texts_batch, rephrase_as_anchor, RateLimitException
from news_service import get_personalized_news
from utils import send_email
from config import FLASK_SECRET_KEY, AI_MODEL_NAME, DATABASE_URL, PERSISTENT_STORAGE_PATH
from models import User, TopicPreference, ApiError
from database import SessionLocal
from extensions import cache

app = Flask(__name__)
app.debug = True
app.secret_key = FLASK_SECRET_KEY
# Load the persistent storage path into the app's config
app.config['PERSISTENT_STORAGE_PATH'] = PERSISTENT_STORAGE_PATH

# Initialize extensions
cache.init_app(app)

@app.before_request
def before_request():
    g.db = SessionLocal()

@app.after_request
def after_request(response):
    g.db.close()
    return response

@app.route('/')
def display_news():
    user_email = session.get('email')
    user = None
    user_id = None
    country_code = None
    region_name = None

    if user_email:
        user = g.db.query(User).filter_by(email=user_email).first()
        if user:
            user_id = user.id
    else:
        # For anonymous users, detect region from IP
        try:
            # Use X-Forwarded-For header if behind a proxy, else fallback to remote_addr
            ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
            
            # If testing locally, use a sample Indian IP for demonstration
            if ip_address == '127.0.0.1':
                ip_address = '202.83.21.1' # Sample IP from India

            # Call a free geolocation API to get country code from IP
            api_response = requests.get(f'http://ip-api.com/json/{ip_address}?fields=country,countryCode')
            api_response.raise_for_status()  # Raise an exception for HTTP errors
            data = api_response.json()
            country_code = data.get('countryCode')
            region_name = data.get('country')
            app.logger.info(f"Detected region '{region_name}' ({country_code}) for IP {ip_address}")
        except requests.exceptions.RequestException as e:
            app.logger.error(f"Could not detect region via IP address due to network error: {e}")
        except Exception as e:
            app.logger.error(f"An unexpected error occurred during IP geolocation: {e}")


     # 1. Check for a search query and category from the user
    search_query = request.args.get('q', None)
    category = request.args.get('category', 'Latest') # Default to 'Latest'

    # 2. Centralized call to the news service, now with country_code for anonymous users
    entries_with_logos = get_personalized_news(db=g.db, user_id=user_id, search_query=search_query, category=category, country_code=country_code)

    # 3. Collect article content for summarization
    # We only process entries that have a 'summary' attribute from the RSS feed.
    texts_to_summarize = []
    entries_with_summary = []
    for entry, logo_url in entries_with_logos:
        if hasattr(entry, 'summary'):
            soup = BeautifulSoup(entry.summary, "html.parser")
            plain_text = soup.get_text()
            texts_to_summarize.append(plain_text[:3000]) # Truncate to avoid large payloads
            entries_with_summary.append(entry)

    try:
        # 4. Batch summarize all valid articles at once for efficiency
        batch_summaries, usage_data = summarize_texts_batch(texts_to_summarize) if texts_to_summarize else ([], None)
    except RateLimitException:
        # If the API limit is hit, fetch the last error time and render a specific error page.
        last_error_time = "an unknown time"
        last_error = g.db.query(ApiError).order_by(ApiError.timestamp.desc()).first()
        if last_error:
            # Format the timestamp for display
            error_dt = last_error.timestamp
            last_error_time = error_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
        else:
            app.logger.warning("Could not fetch last API error time from DB because no errors were found.")
        return render_template('rate_limit.html', last_error_time=last_error_time), 503

    # Log the token usage for the summarization call
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

    # 5. Map summaries back to their original articles
    # Create a dictionary to map entry links to their summaries for easy lookup
    summary_map = {}
    if batch_summaries and len(batch_summaries) == len(entries_with_summary):
        for i, entry in enumerate(entries_with_summary):
            summary_map[entry.link] = batch_summaries[i]

    # Build the final list of summaries in the same order as the original combined_entries
    summaries = [summary_map.get(entry.link, "No summary available for this article.") for entry, logo_url in entries_with_logos]

    if summaries:
        # Store the combined text in the session for the audio generation route to use
        session['combined_summaries'] = " ".join(summaries)
    else:
        # Clear it if there are no summaries
        session.pop('combined_summaries', None)

    # 6. Render the main page with all the data
    return render_template('index.html', entries_with_logos=entries_with_logos, summaries=summaries, user=user, search_query=search_query, category=category, region_name=region_name)


@app.route('/generate_audio') # Changed to GET, no longer needs POST
def generate_audio():
    """Generates the news anchor script and audio file on-demand."""
    app.logger.info("--- Starting Audio Generation ---")
    cache.delete_memoized(rephrase_as_anchor) # Clear specific cache for a fresh AI call
    
    combined_summaries = session.get('combined_summaries')
    if not combined_summaries:
        app.logger.error("Audio generation failed: No summaries found in session.")
        return jsonify({'error': 'No summaries available to generate audio.'}), 404
    app.logger.info(f"Summaries retrieved from session. Length: {len(combined_summaries)}")

    try:
        app.logger.info("Requesting anchor script from AI...")
        anchor_script, usage_data = rephrase_as_anchor(combined_summaries)
        app.logger.info("Successfully received anchor script from AI.")
        
        if not anchor_script or not anchor_script.strip():
            app.logger.error("AI service returned an empty anchor script.")
            return jsonify({'error': 'Failed to generate a valid news script from the AI service.'}), 500
    except RateLimitException:
        app.logger.error("AI rate limit exceeded during anchor script generation.")
        return jsonify({'error': 'AI limit exceeded by the website server, please try again in 24 hours'}), 503
    except Exception as e:
        app.logger.error(f"An unexpected error occurred during anchor script generation: {e}")
        return jsonify({'error': 'An internal error occurred while generating the news script.'}), 500

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

    filename_hash = hashlib.md5(anchor_script.encode()).hexdigest()
    audio_filename = f"{filename_hash}.mp3"

    storage_path = app.config['PERSISTENT_STORAGE_PATH']
    os.makedirs(storage_path, exist_ok=True)
    audio_filepath = os.path.join(storage_path, audio_filename)
    app.logger.info(f"Audio file will be saved to: {audio_filepath}")

    if not os.path.exists(audio_filepath):
        try:
            app.logger.info("Generating new audio file with gTTS...")
            tts = gTTS(text=anchor_script, lang='en')
            tts.save(audio_filepath)
            app.logger.info("Audio file saved successfully.")
        except Exception as e:
            app.logger.error(f"Failed to generate or save audio file with gTTS: {e}")
            return jsonify({'error': 'The server encountered an error while creating the audio file.'}), 500
    else:
        app.logger.info("Audio file already exists. Serving from cache.")

    audio_url = url_for('serve_media', filename=audio_filename)
    app.logger.info(f"--- Audio Generation Complete. Returning URL: {audio_url} ---")
    return jsonify({'audio_file': audio_url})

@app.route('/media/<path:filename>')
def serve_media(filename):
    """Serves files from the persistent storage directory."""
    storage_path = app.config.get('PERSISTENT_STORAGE_PATH')
    if not storage_path or not os.path.isdir(storage_path):
        return "Media storage not configured or not found on the server.", 500
    return send_from_directory(storage_path, filename)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'email' in session:
        flash('You are already logged in.', 'info')
        return redirect(url_for('display_news'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        hashed_password = generate_password_hash(password)

        try:
            # Check if user already exists
            existing_user = g.db.query(User).filter_by(email=email).first()
            if existing_user:
                flash('An account with this email already exists.', 'danger')
                return redirect(url_for('register'))

            new_user = User(email=email, password=hashed_password)
            g.db.add(new_user)
            g.db.commit()

            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            # Log the detailed error for debugging and show a generic message to the user.
            app.logger.critical(f"Database error during registration for '{email}': {e}")
            flash('An error occurred during registration. Please try again later.', 'danger')
            return render_template('register.html', user=None), 500

    return render_template('register.html', user=None)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'email' in session:
        return redirect(url_for('loading'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = g.db.query(User).filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            session['email'] = user.email
            app.logger.info(f"User '{email}' logged in successfully.")
            return redirect(url_for('display_news'))
        else:
            # Log a failed login attempt for security awareness
            flash('Invalid email or password.', 'danger')
            app.logger.warning(f"Failed login attempt for email: '{email}'")

    return render_template('login.html', user=None)

@app.route('/logout')
def logout():
    session.pop('email', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        user = g.db.query(User).filter_by(email=email).first()

        if user:
            s = URLSafeTimedSerializer(app.secret_key)
            token = s.dumps(email, salt='password-reset-salt')
            
            user.reset_token = token
            user.reset_token_expiry = datetime.now() + timedelta(hours=1)
            g.db.commit()
            
            reset_url = url_for('reset_password', token=token, _external=True)
            subject = "Password Reset Request"
            body = f"""To reset your password, visit the following link:
{reset_url}

If you did not make this request then simply ignore this email and no changes will be made.
This link will expire in 1 hour.
"""
            send_email(email, subject, body)
        
        # Flash message regardless of whether user exists to prevent enumeration
        flash('If that email address is in our database, a password reset link has been sent.', 'info')
        return redirect(url_for('login'))

    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    s = URLSafeTimedSerializer(app.secret_key)
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600)  # 1 hour
    except Exception:
        flash('The password reset link is invalid or has expired.', 'danger')
        return redirect(url_for('login'))

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

        hashed_password = generate_password_hash(password)

        user.password = hashed_password
        user.reset_token = None
        user.reset_token_expiry = None
        g.db.commit()
        app.logger.info(f"Password reset successfully for user {email}")

        flash('Your password has been successfully reset. Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('reset_password.html', token=token)

@app.route('/preferences', methods=['GET', 'POST'])
def preferences():
    if 'email' not in session:
        flash('You must be logged in to view this page.', 'warning')
        return redirect(url_for('login'))

    email = session['email']
    user = g.db.query(User).filter_by(email=email).first()

    if not user:
        session.pop('email', None)
        flash('User not found. Please log in again.', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        user.preferred_category = request.form['category']
        user.preferred_region = request.form.get('region')

        # Using the relationship is much cleaner for updating topics
        # First, remove all existing topic preferences for the user
        g.db.query(TopicPreference).filter_by(user_id=user.id).delete()

        # Then, add the new ones
        new_topics = [request.form[f'topic{i}'] for i in range(1, 6) if request.form.get(f'topic{i}')]
        for topic_name in new_topics:
            topic_pref = TopicPreference(user_id=user.id, topic_name=topic_name)
            g.db.add(topic_pref)

        g.db.commit()
        flash('Your preferences have been saved!', 'success')
        return redirect(url_for('preferences'))

    # For GET request, fetch current preferences via the relationship
    followed_topics = [topic.topic_name for topic in user.topics]

    return render_template('preferences.html',
                           news_feeds=NEWS_FEEDS,
                           regions=REGIONS,
                           user=user,
                           followed_topics=followed_topics)

if __name__ == '__main__':
    with app.app_context():
        cache.clear()  # Clear the cache
        app.run(debug=True, threaded=True)
