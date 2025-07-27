"""
News Fetching Service (news_service.py)

This module is responsible for fetching personalized news content for users.
It interacts with the database to retrieve user preferences (preferred category,
followed topics, and region) and then constructs the appropriate Google News RSS
feed URLs to fetch the relevant articles. It also provides a fallback to
default "Top Stories" if no user is specified or if no preferences are set.
"""
import sqlite3
import feedparser
from urllib.parse import quote
import logging

from constants import NEWS_FEEDS
from utils import build_full_url

logger = logging.getLogger(__name__)

def get_personalized_news(user_id=None):
    """
    Fetches personalized news for a given user_id.
    - Fetches a total of 10 articles based on user's preferred category and/or followed topics.
    - If no user_id is provided or no articles are found, fetches 10 default Top Stories.
    """
    combined_entries = []
    user_region = None

    if user_id:
        try:
            with sqlite3.connect('newsapp.db') as conn:
                cursor = conn.cursor()

                # 1. Get all preferences first to determine the fetching strategy
                cursor.execute("SELECT preferred_category, preferred_region FROM users WHERE id = ?", (user_id,))
                user_prefs = cursor.fetchone()
                preferred_category, user_region = (user_prefs[0], user_prefs[1]) if user_prefs else (None, None)

                cursor.execute("SELECT topic_name FROM topic_preferences WHERE user_id = ?", (user_id,))
                topics = cursor.fetchall()

                has_category = bool(preferred_category and preferred_category in NEWS_FEEDS)
                has_topics = bool(topics)

                # 2. Determine how many articles to fetch from each source to total 10
                category_limit = 0
                topic_limit = 0
                if has_category and has_topics:
                    category_limit = 5
                    topic_limit = 5
                elif has_category:
                    category_limit = 10
                elif has_topics:
                    topic_limit = 10

                # 3. Fetch from category if applicable
                if category_limit > 0:
                    category_url = NEWS_FEEDS[preferred_category]
                    full_url = build_full_url(category_url, user_region)
                    logger.info(f"Fetching {category_limit} news from category URL: {full_url}")
                    combined_entries.extend(feedparser.parse(full_url).entries[:category_limit])

                # 4. Fetch from topics if applicable
                if topic_limit > 0:
                    topic_names = [t[0] for t in topics]
                    search_query = " OR ".join(topic_names)
                    topic_url = f"https://news.google.com/rss/search?q={quote(search_query)}"
                    full_url = build_full_url(topic_url, user_region)
                    logger.info(f"Fetching {topic_limit} news from topic URL: {full_url}")
                    combined_entries.extend(feedparser.parse(full_url).entries[:topic_limit])

        except sqlite3.Error as e:
            logger.error(f"Database error while fetching news for user {user_id}: {e}")
            # Continue with empty entries, will fall back to default

    # 5. Fallback to default if no user, no preferences, or no articles found
    if not combined_entries:
        logger.info("No preferences found or no articles fetched, getting default Top Stories.")
        default_url = NEWS_FEEDS['Top Stories']
        # Apply region if user is logged in and has one set
        full_url = build_full_url(default_url, user_region)
        feed = feedparser.parse(full_url)
        combined_entries.extend(feed.entries[:10])

    return combined_entries