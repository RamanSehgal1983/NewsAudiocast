"""
Application Constants (constants.py)

This file defines static, non-sensitive data that is used throughout the application.
Storing constants here makes them easy to manage and modify without changing the
core application logic.

Includes:
- NEWS_FEEDS: A dictionary mapping news category names to their Google News RSS feed URLs.
- REGIONS: A nested dictionary organizing countries and their codes by continent for
           regional news filtering.
"""
NEWS_FEEDS = {
    'Top Stories': 'https://news.google.com/rss',
    'World': 'https://news.google.com/rss/headlines/section/topic/WORLD',
    'Business': 'https://news.google.com/rss/headlines/section/topic/BUSINESS',
    'Technology': 'https://news.google.com/rss/headlines/section/topic/TECHNOLOGY',
    'Sports': 'https://news.google.com/rss/headlines/section/topic/SPORTS',
    'Fashion': 'https://news.google.com/rss/search?q=fashion',
    'AI': 'https://news.google.com/rss/search?q=AI',
    'Defence': 'https://news.google.com/rss/search?q=defence',
    'Information Technology': 'https://news.google.com/rss/search?q=information%20technology',
    'Weather': 'https://news.google.com/rss/search?q=weather'
}

REGIONS = {
    'Asia': [('India', 'IN'), ('China', 'CN'), ('Japan', 'JP'), ('South Korea', 'KR')],
    'Africa': [('South Africa', 'ZA')],
    'Middle East': [('Saudi Arabia', 'SA'), ('UAE', 'AE'), ('Iran', 'IR'), ('Iraq', 'IQ'), ('Israel', 'IL')],
    'Europe': [('European Union', 'EU'), ('France', 'FR'), ('Germany', 'DE'), ('Italy', 'IT'), ('Russia', 'RU'), ('Spain', 'ES'), ('UK', 'GB')],
    'North America': [('USA', 'US'), ('Canada', 'CA'), ('Mexico', 'MX')],
    'South America': [('Argentina', 'AR'), ('Brazil', 'BR'), ('Chile', 'CL'), ('Colombia', 'CO')],
    'Oceania': [('Australia', 'AU'), ('New Zealand', 'NZ'), ('Singapore', 'SG')]
}