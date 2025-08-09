"""
News Fetching Service (news_service.py)

This module is responsible for fetching personalized news content for users.
It interacts with the database to retrieve user preferences (preferred category,
followed topics, and region) and then constructs the appropriate Google News RSS
feed URLs to fetch the relevant articles. It also provides a fallback to
default "Top Stories" if no user is specified or if no preferences are set.
"""
# Import necessary libraries
import feedparser  # For parsing RSS feeds from Google News
from urllib.parse import quote, urlparse  # For URL-encoding search queries and parsing URLs
import logging  # For logging information and errors
from sqlalchemy.exc import SQLAlchemyError  # For handling database errors

# Import custom modules and components
from constants import NEWS_FEEDS  # Predefined RSS feed URLs
from utils import build_full_url  # Helper function to construct final URLs
from models import User  # The User database model
from database import SessionLocal  # The database session
from extensions import cache  # The caching mechanism

# Set up a logger for this module to record events
logger = logging.getLogger(__name__)


def _get_logo_url_from_entry(entry):
    """Constructs a favicon URL from the entry's source or link."""
    url_to_parse = None
    # Prioritize the source link if it exists, as it's more reliable for the publisher's domain
    if hasattr(entry, 'source') and entry.source and hasattr(entry.source, 'href') and entry.source.href:
        url_to_parse = entry.source.href
    # Fallback to the entry link if no source is available
    elif hasattr(entry, 'link') and entry.link:
        url_to_parse = entry.link

    if url_to_parse:
        try:
            hostname = urlparse(url_to_parse).hostname
            if hostname:
                # Use a favicon service. Google's is reliable.
                # sz=64 requests a 64x64 pixel icon.
                return f"https://www.google.com/s2/favicons?domain={hostname}&sz=64"
        except Exception as e:
            logger.warning(f"Could not parse URL to get hostname for favicon: {url_to_parse}, Error: {e}")
    return None


def _parse_feed_and_get_entries(feed_url, limit):
    """Parses a feed and returns entries with their logo URLs."""
    logger.info(f"Attempting to parse feed from URL: {feed_url}")
    try:
        feed = feedparser.parse(feed_url)
        if feed.bozo:
            logger.warning(f"Feed parsing error for {feed_url}: {feed.bozo_exception}")
        logger.info(f"Found {len(feed.entries)} entries for URL: {feed_url}")
        entries_with_logos = []
        for entry in feed.entries[:limit]:
            logo_url = _get_logo_url_from_entry(entry)
            entries_with_logos.append((entry, logo_url))
        return entries_with_logos
    except Exception as e:
        logger.error(f"Error parsing feed from {feed_url}: {e}")
        return []


@cache.memoize(timeout=900)
def get_personalized_news(db, user_id=None, search_query=None, country_code=None, category=None):
    """
    Fetches personalized news for a given user.

    This function does a few things:
    1. If a search term is provided, it finds news related to that term.
    2. If not, it looks at the user's saved preferences (favorite category and topics).
    3. If the user has no preferences, it fetches the default "Top Stories".
    4. It tries to use the user's preferred country for the news, otherwise, it defaults to worldwide.
    """
    try:
        user = db.query(User).filter(User.id == user_id).first() if user_id else None

        final_region_code = None
        if user and user.preferred_region:
            final_region_code = user.preferred_region
        elif country_code:
            final_region_code = country_code

        if search_query:
            logger.info(f"Performing news search for query: '{search_query}'")
            search_url = f"https://news.google.com/rss/search?q={quote(search_query)}"
            full_url = build_full_url(search_url, final_region_code)
            logger.info(f"Search URL: {full_url}")
            return _parse_feed_and_get_entries(full_url, 10)

        if category and category in NEWS_FEEDS:
            logger.info(f"Fetching news for category: '{category}'")
            category_url = NEWS_FEEDS[category]
            full_url = build_full_url(category_url, final_region_code)
            logger.info(f"Category URL: {full_url}")
            return _parse_feed_and_get_entries(full_url, 10)

        combined_entries_with_logos = []
        preferred_category = None
        topics = []

        if user:
            try:
                preferred_category = user.preferred_category
                topics = [pref.topic_name for pref in user.topics]
                has_category = bool(preferred_category and preferred_category in NEWS_FEEDS)
                has_topics = bool(topics)

                category_limit = 0
                topic_limit = 0
                if has_category and has_topics:
                    category_limit = 5
                    topic_limit = 5
                elif has_category:
                    category_limit = 10
                elif has_topics:
                    topic_limit = 10

                if category_limit > 0:
                    category_url = NEWS_FEEDS[preferred_category]
                    full_url = build_full_url(category_url, final_region_code)
                    logger.info(f"Fetching {category_limit} news from category URL: {full_url}")
                    combined_entries_with_logos.extend(_parse_feed_and_get_entries(full_url, category_limit))

                if topic_limit > 0:
                    search_query_topics = " OR ".join(topics)
                    topic_url = f"https://news.google.com/rss/search?q={quote(search_query_topics)}"
                    full_url = build_full_url(topic_url, final_region_code)
                    logger.info(f"Fetching {topic_limit} news from topic URL: {full_url}")
                    combined_entries_with_logos.extend(_parse_feed_and_get_entries(full_url, topic_limit))
            except SQLAlchemyError as e:
                logger.error(f"Database error while fetching news for user {user_id}: {e}")

        if not combined_entries_with_logos:
            logger.info("No preferences found or no articles fetched, getting default Top Stories.")
            default_url = NEWS_FEEDS['Top Stories']
            full_url = build_full_url(default_url, final_region_code)
            logger.info(f"Default Top Stories URL: {full_url}")
            combined_entries_with_logos.extend(_parse_feed_and_get_entries(full_url, 10))

        logger.info(f"Total combined entries fetched: {len(combined_entries_with_logos)}")
        return combined_entries_with_logos
    except Exception as e:
        logger.error(f"An unexpected error occurred in get_personalized_news: {e}")
        # Re-raise the exception or handle it as appropriate for your application
        raise
