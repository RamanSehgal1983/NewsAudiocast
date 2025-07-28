"""
News Fetching Service (news_service.py)

This module is responsible for fetching personalized news content for users.
It interacts with the database to retrieve user preferences (preferred category,
followed topics, and region) and then constructs the appropriate Google News RSS
feed URLs to fetch the relevant articles. It also provides a fallback to
default "Top Stories" if no user is specified or if no preferences are set.
"""
import feedparser
from urllib.parse import quote
import logging
from sqlalchemy.exc import SQLAlchemyError

from constants import NEWS_FEEDS
from utils import build_full_url
from models import User
from database import SessionLocal
from extensions import cache

logger = logging.getLogger(__name__)

@cache.memoize(timeout=900)  # Cache results for 15 minutes
def get_personalized_news(user_id=None):
    """
    Fetches personalized news for a given user_id using SQLAlchemy.
    - Fetches a total of 10 articles based on user's preferred category and/or followed topics.
    - If no user_id is provided or no articles are found, fetches 10 default Top Stories.
    """
    combined_entries = []
    user_region = None
    preferred_category = None
    topics = []

    if user_id:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                preferred_category = user.preferred_category
                user_region = user.preferred_region
                # Use the ORM relationship to get followed topics directly
                topics = [pref.topic_name for pref in user.topics]

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
                search_query = " OR ".join(topics)
                topic_url = f"https://news.google.com/rss/search?q={quote(search_query)}"
                full_url = build_full_url(topic_url, user_region)
                logger.info(f"Fetching {topic_limit} news from topic URL: {full_url}")
                combined_entries.extend(feedparser.parse(full_url).entries[:topic_limit])
        except SQLAlchemyError as e:
            logger.error(f"Database error while fetching news for user {user_id}: {e}")
            # Continue with empty entries, will fall back to default
        finally:
            db.close()

    # 5. Fallback to default if no user, no preferences, or no articles found
    if not combined_entries:
        logger.info("No preferences found or no articles fetched, getting default Top Stories.")
        default_url = NEWS_FEEDS['Top Stories']
        # Apply region if user is logged in and has one set
        full_url = build_full_url(default_url, user_region)
        feed = feedparser.parse(full_url)
        combined_entries.extend(feed.entries[:10])

    return combined_entries