"""
Flask Extensions (extensions.py)

This file is used to instantiate Flask extensions to avoid circular import issues.
By creating the extension objects here and initializing them in the app factory,
they can be safely imported into any other module (like blueprints or services).
"""
from flask_caching import Cache

# Configure cache with a simple in-memory type. For production, consider 'redis' or 'memcached'.
cache = Cache(config={'CACHE_TYPE': 'simple', 'CACHE_DEFAULT_TIMEOUT': 300})
