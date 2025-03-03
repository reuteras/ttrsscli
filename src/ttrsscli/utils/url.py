"""URL utility functions for ttrsscli."""

import logging

from cleanurl import Result, cleanurl

logger: logging.Logger = logging.getLogger(name=__name__)

def get_clean_url(url: str, clean_url_enabled: bool = True) -> str:
    """Clean URL using cleanurl if enabled.

    Args:
        url: URL to clean
        clean_url_enabled: Whether to clean URLs

    Returns:
        Cleaned URL or original URL
    """
    if not url:
        return ""

    if clean_url_enabled:
        try:
            cleaned_url: Result | None = cleanurl(url=url)
            if cleaned_url:
                return cleaned_url.url
        except Exception as e:
            logger.debug(msg=f"Error cleaning URL {url}: {e}")

    return url