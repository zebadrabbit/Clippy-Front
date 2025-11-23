"""
Caching configuration for ClippyFront.

Provides Redis-backed caching for performance optimization:
- Platform preset settings (10-20ms savings per lookup)
- User tags (50-100ms savings on media library loads)
- Tag autocomplete (30-50ms savings per search)
"""

from flask_caching import Cache

# Initialize cache instance
cache = Cache()


def init_cache(app):
    """
    Initialize Flask-Caching with Redis backend.

    Falls back to SimpleCache for development if Redis unavailable.

    Args:
        app: Flask application instance
    """
    cache_config = {
        "CACHE_TYPE": "redis" if app.config.get("REDIS_URL") else "SimpleCache",
        "CACHE_DEFAULT_TIMEOUT": 300,  # 5 minutes default
        "CACHE_KEY_PREFIX": "clippy:",
    }

    if app.config.get("REDIS_URL"):
        cache_config["CACHE_REDIS_URL"] = app.config["REDIS_URL"]

    app.config.update(cache_config)
    cache.init_app(app)

    app.logger.info(
        f"Cache initialized: {cache_config['CACHE_TYPE']} backend",
        extra={"cache_type": cache_config["CACHE_TYPE"]},
    )

    return cache


def invalidate_user_tags_cache(user_id):
    """
    Invalidate tag cache for a specific user.

    Called after tag CRUD operations.

    Args:
        user_id: User ID whose tag cache should be invalidated
    """
    cache.delete_memoized("get_user_tags", user_id)


def invalidate_tag_autocomplete_cache():
    """
    Invalidate tag autocomplete cache.

    Called after tag creation or deletion.
    """
    # Delete all keys matching tag autocomplete pattern
    cache.delete_memoized("tag_autocomplete_search")
