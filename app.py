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
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from gtts import gTTS
import os
import hashlib
import sqlite3
from itsdangerous import URLSafeTimedSerializer
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash, check_password_hash
from bs4 import BeautifulSoup
from constants import NEWS_FEEDS, REGIONS
from ai_utils import summarize_texts_batch, rephrase_as_anchor, RateLimitException
from news_service import get_personalized_news
from utils import send_email
from config import FLASK_SECRET_KEY

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

@app.route('/')
def display_news():
    user_email = session.get('email')
    user = None
    user_id = None

    if user_email:
        with sqlite3.connect('newsapp.db') as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (user_email,))
            user = cursor.fetchone()
            if user:
                user_id = user['id']

    # Centralized call to the news service
    # It handles both logged-in (with user_id) and anonymous (user_id=None) users
    combined_entries = get_personalized_news(user_id)

    # Collect texts from entries that have a summary
    texts_to_summarize = []
    entries_with_summary = []
    for entry in combined_entries:
        if hasattr(entry, 'summary'):
            soup = BeautifulSoup(entry.summary, "html.parser")
            plain_text = soup.get_text()
            texts_to_summarize.append(plain_text[:3000])
            entries_with_summary.append(entry)

    try:
        # Batch summarize all valid articles at once
        batch_summaries = summarize_texts_batch(texts_to_summarize) if texts_to_summarize else []
    except RateLimitException:
        # If the API limit is hit, fetch the last error time and render a specific error page.
        last_error_time = "an unknown time"
        try:
            with sqlite3.connect('newsapp.db') as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT timestamp FROM api_errors ORDER BY timestamp DESC LIMIT 1")
                last_error = cursor.fetchone()
                if last_error:
                    # Format the timestamp for display
                    error_dt = datetime.fromisoformat(last_error[0])
                    last_error_time = error_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
        except sqlite3.Error as e:
            app.logger.error(f"Could not fetch last API error time from DB: {e}")
        return render_template('rate_limit.html', last_error_time=last_error_time), 503

    # Create a dictionary to map entry links to their summaries for easy lookup
    summary_map = {}
    if batch_summaries and len(batch_summaries) == len(entries_with_summary):
        for i, entry in enumerate(entries_with_summary):
            summary_map[entry.link] = batch_summaries[i]

    # Build the final list of summaries in the same order as the original entries
    summaries = [summary_map.get(entry.link, "No summary available for this article.") for entry in combined_entries]

    # If there are summaries, combine them and store in the session for on-demand audio generation.
    if batch_summaries:
        combined_summaries = " ".join(batch_summaries)
        session['combined_summaries'] = combined_summaries
    else:
        session.pop('combined_summaries', None)

    return render_template('index.html', entries=combined_entries, summaries=summaries, user=user)

@app.route('/generate_audio')
def generate_audio():
    """Generates the news anchor script and audio file on-demand."""
    combined_summaries = session.get('combined_summaries')
    if not combined_summaries:
        return jsonify({'error': 'No summaries available to generate audio.'}), 404

    try:
        anchor_script = rephrase_as_anchor(combined_summaries)
    except RateLimitException:
        return jsonify({'error': 'AI limit exceeded by the website server, please try again in 24 hours'}), 503

    filename_hash = hashlib.md5(anchor_script.encode()).hexdigest()
    audio_filename = f"{filename_hash}.mp3"
    audio_filepath = os.path.join('static', audio_filename)

    if not os.path.exists(audio_filepath):
        tts = gTTS(text=anchor_script, lang='en')
        tts.save(audio_filepath)

    return jsonify({'audio_file': url_for('static', filename=audio_filename)})

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        hashed_password = generate_password_hash(password)

        # Using 'with' for safe database connection handling
        with sqlite3.connect('newsapp.db') as conn:
            cursor = conn.cursor()
            # Check if user already exists
            cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
            if cursor.fetchone():
                flash('An account with this email already exists.', 'danger')
                return redirect(url_for('register'))

            cursor.execute("INSERT INTO users (email, password) VALUES (?, ?)", (email, hashed_password))
            conn.commit()

        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        with sqlite3.connect('newsapp.db') as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            user = cursor.fetchone()

        if user and check_password_hash(user['password'], password):
            session['email'] = user['email']
            app.logger.info(f"User '{email}' logged in successfully.")
            return redirect(url_for('loading'))
        else:
            # Log a failed login attempt for security awareness
            flash('Invalid email or password.', 'danger')
            app.logger.warning(f"Failed login attempt for email: '{email}'")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('email', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        with sqlite3.connect('newsapp.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            user = cursor.fetchone()

            if user:
                s = URLSafeTimedSerializer(app.secret_key)
                token = s.dumps(email, salt='password-reset-salt')
                
                expiry = datetime.now() + timedelta(hours=1)
                cursor.execute("UPDATE users SET reset_token = ?, reset_token_expiry = ? WHERE email = ?",
                               (token, expiry, email))
                conn.commit()
                
                # Construct and send the email using the new utility
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

    with sqlite3.connect('newsapp.db') as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE email = ? AND reset_token = ? AND reset_token_expiry > ?",
            (email, token, datetime.now())
        )
        user = cursor.fetchone()

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

        with sqlite3.connect('newsapp.db') as conn:
            cursor = conn.cursor()
            # Update password and clear reset token fields
            cursor.execute(
                "UPDATE users SET password = ?, reset_token = NULL, reset_token_expiry = NULL WHERE email = ?",
                (hashed_password, email)
            )
            conn.commit()
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
    with sqlite3.connect('newsapp.db') as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Fetch user data
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()

        if not user:
            session.pop('email', None)
            flash('User not found. Please log in again.', 'danger')
            return redirect(url_for('login'))

        user_id = user['id']

        if request.method == 'POST':
            category = request.form['category']
            region = request.form.get('region')
            topics = [request.form[f'topic{i}'] for i in range(1, 6) if request.form.get(f'topic{i}')]

            # Update user's category and region
            cursor.execute("UPDATE users SET preferred_category = ?, preferred_region = ? WHERE id = ?",
                           (category, region, user_id))

            # Update followed topics
            cursor.execute("DELETE FROM topic_preferences WHERE user_id = ?", (user_id,))
            if topics:
                cursor.executemany("INSERT INTO topic_preferences (user_id, topic_name) VALUES (?, ?)",
                                   [(user_id, topic) for topic in topics])
            
            conn.commit()
            flash('Your preferences have been saved!', 'success')
            return redirect(url_for('preferences'))

        # For GET request, fetch current preferences
        cursor.execute("SELECT topic_name FROM topic_preferences WHERE user_id = ?", (user_id,))
        followed_topics = [row['topic_name'] for row in cursor.fetchall()]

    return render_template('preferences.html',
                           news_feeds=NEWS_FEEDS,
                           regions=REGIONS,
                           user=user,
                           followed_topics=followed_topics)

@app.route('/loading')
def loading():
    # This route is hit right after login. It needs the user object
    # to render the navigation bar correctly.
    user = None
    if 'email' in session:
        with sqlite3.connect('newsapp.db') as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (session['email'],))
            user = cursor.fetchone()

    return render_template('loading.html', user=user)