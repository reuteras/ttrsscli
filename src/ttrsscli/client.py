"""Client module for ttrsscli."""

import logging
from typing import Any

from ttrss.client import Article, Category, Feed, Headline, TTRClient

from .utils.decorators import handle_session_expiration

logger: logging.Logger = logging.getLogger(name=__name__)


class TTRSSClient:
    """A wrapper for ttrss-python to reauthenticate on failure and provide caching."""

    def __init__(self, url, username, password) -> None:
        """Initialize the TTRSS client."""
        self.url: str = url
        self.username: str = username
        self.password: str = password
        self.api = TTRClient(
            url=self.url, user=self.username, password=self.password, auto_login=False
        )
        self.login()
        self.cache = {}  # Simple cache to reduce API calls

    def login(self) -> bool:
        """Authenticate with TTRSS and store session.

        Returns:
            True if login successful, False otherwise
        """
        try:
            # Force reinitialization of the session to clear any stale cookies
            self.api = TTRClient(
                url=self.url,
                user=self.username,
                password=self.password,
                auto_login=False
            )

            # Get a new session ID
            self.api.login()

            # Verify login status to make sure it worked
            if hasattr(self.api, 'logged_in') and callable(self.api.logged_in):
                is_logged_in: bool = self.api.logged_in()
                if not is_logged_in:
                    logger.warning(msg="Login appeared successful but session is not valid.")
                    return False

            logger.info(msg="Successfully authenticated with TTRSS")
            return True
        except Exception as e:
            logger.error(msg=f"Login failed: {e}")
            return False

    @handle_session_expiration
    def get_articles(self, article_id) -> list[Article]:
        """Fetch article content, retrying if session expires."""
        cache_key: str = f"article_{article_id}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            articles: list[Article] = self.api.get_articles(article_id=article_id)
        except Exception as e:
            logger.error(msg=f"Error fetching article {article_id}: {e}")
            return []
        self.cache[cache_key] = articles
        return articles

    @handle_session_expiration
    def get_categories(self) -> list[Category]:
        """Fetch category list, retrying if session expires."""
        cache_key = "categories"
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            categories: list[Category] = self.api.get_categories()
        except Exception as e:
            logger.error(msg=f"Error fetching categories: {e}")
            return []
        self.cache[cache_key] = categories
        return categories

    @handle_session_expiration
    def get_feeds(self, cat_id, unread_only) -> list[Feed]:
        """Fetch feed list, retrying if session expires."""
        cache_key: str = f"feeds_{cat_id}_{unread_only}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            feeds: list[Feed] = self.api.get_feeds(cat_id=cat_id, unread_only=unread_only)
        except Exception as e:
            logger.error(msg=f"Error fetching feeds for category {cat_id}: {e}")
            return []
        self.cache[cache_key] = feeds
        return feeds

    @handle_session_expiration
    def get_headlines(self, feed_id, is_cat, view_mode) -> list[Headline]:
        """Fetch headlines for a feed, retrying if session expires."""
        cache_key: str = f"headlines_{feed_id}_{is_cat}_{view_mode}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            headlines: list[Headline] = self.api.get_headlines(
                feed_id=feed_id, is_cat=is_cat, view_mode=view_mode
            )
        except Exception as e:
            logger.error(msg=f"Error fetching headlines for feed {feed_id}: {e}")
            return []
        self.cache[cache_key] = headlines
        return headlines

    @handle_session_expiration
    def mark_read(self, article_id) -> None:
        """Mark article as read, retrying if session expires."""
        try:
            self.api.mark_read(article_id=article_id)
        except Exception as e:
            logger.error(msg=f"Error marking article {article_id} as read: {e}")
        # Invalidate relevant cache entries
        self._invalidate_headline_cache()

    @handle_session_expiration
    def mark_unread(self, article_id) -> None:
        """Mark article as unread, retrying if session expires."""
        try:
            self.api.mark_unread(article_id=article_id)
        except Exception as e:
            logger.error(msg=f"Error marking article {article_id} as unread: {e}")
        # Invalidate relevant cache entries
        self._invalidate_headline_cache()

    @handle_session_expiration
    def toggle_starred(self, article_id) -> None:
        """Toggle article starred, retrying if session expires."""
        try:
            self.api.toggle_starred(article_id=article_id)
        except Exception as e:
            logger.error(msg=f"Error toggling starred for article {article_id}: {e}")
        # Invalidate article cache
        if f"article_{article_id}" in self.cache:
            del self.cache[f"article_{article_id}"]

    @handle_session_expiration
    def toggle_unread(self, article_id) -> None:
        """Toggle article read/unread, retrying if session expires."""
        try:
            self.api.toggle_unread(article_id=article_id)
        except Exception as e:
            logger.error(msg=f"Error toggling read/unread for article {article_id}: {e}")
        # Invalidate relevant cache entries
        if f"article_{article_id}" in self.cache:
            del self.cache[f"article_{article_id}"]
        self._invalidate_headline_cache()

    @handle_session_expiration
    def subscribe_to_feed(self, feed_url, category_id=0, feed_title=None, login=None, password=None) -> Any:
        """Subscribe to a new feed."""
        try:
            response = self.api.subscribe(
                feed_url=feed_url,
                category_id=category_id,
                feed_title=feed_title,
                login=login,
                password=password
            )
        except Exception as e:
            logger.error(msg=f"Error subscribing to feed: {e}")
            return None

        # Clear relevant cache entries
        self._invalidate_headline_cache()

        return response

    @handle_session_expiration
    def unsubscribe_feed(self, feed_id) -> Any:
        """Unsubscribe from a feed (delete it)."""
        try:
            response = self.api.unsubscribe(feed_id=feed_id)
        except Exception as e:
            logger.error(msg=f"Error unsubscribing from feed: {e}")
            return None

        # Clear relevant cache entries
        self._invalidate_headline_cache()

        return response

    @handle_session_expiration
    def get_feed_properties(self, feed_id) -> Any:  # noqa: PLR0912
        """Get properties for a specific feed."""
        cache_key: str = f"feed_properties_{feed_id}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        # Try to get feed properties directly
        feed_props: None | Feed = self.api.get_feed_properties(feed_id=feed_id)

        # If we got valid feed properties
        if feed_props:
            # If the feed URL is missing, try to fetch it from feed tree
            if not hasattr(feed_props, 'feed_url') or not feed_props.feed_url:  # type: ignore
                try:
                    # Get the feed tree to extract URL
                    feed_tree = self.api.get_feed_tree(include_empty=True)

                    # Define a recursive function to search for feed URL in the tree
                    def find_feed_url(items, target_id):
                        for item in items:
                            if item.get('id') == f"FEED:{target_id}" and 'feed_url' in item:
                                return item['feed_url']
                            if 'items' in item:
                                result = find_feed_url(items=item['items'], target_id=target_id)
                                if result:
                                    return result
                        return None

                    # Search for the feed URL in the tree
                    if 'items' in feed_tree['content']:
                        feed_url = find_feed_url(items=feed_tree['content']['items'], target_id=feed_id)
                        if feed_url:
                            # Add the feed_url attribute to feed_props
                            feed_props.feed_url = feed_url  # type: ignore
                except Exception as e:
                    logger.debug(msg=f"Error retrieving feed URL from tree: {e}")

            # Cache the result
            self.cache[cache_key] = feed_props

        # If direct method failed, try to find the feed in all categories
        if not feed_props:
            logger.info(msg=f"Trying to find feed {feed_id} in all feeds")
            all_feeds = []
            try:
                categories: list[Category] = self.get_categories()
                for category in categories:
                    try:
                        feeds: list[Feed] = self.get_feeds(cat_id=category.id, unread_only=False) # type: ignore
                        all_feeds.extend(feeds)
                    except Exception as feed_err:
                        logger.warning(msg=f"Error getting feeds for category {category.id}: {feed_err}") # type: ignore

                # Find the feed in all_feeds
                for feed in all_feeds:
                    if int(feed.id) == int(feed_id):
                        feed_props = feed

                        # Try to get feed URL from feed tree if not available
                        if not feed_props is None and (not hasattr(feed_props, 'feed_url') or (hasattr(feed_props, 'feed_url') and not feed_props.feed_url)): # type: ignore
                            try:
                                feed_tree = self.api.get_feed_tree(include_empty=True)

                                def find_feed_url(items, target_id):
                                    for item in items:
                                        if item.get('id') == f"FEED:{target_id}" and 'feed_url' in item:
                                            return item['feed_url']
                                        if 'items' in item:
                                            result = find_feed_url(items=item['items'], target_id=target_id)
                                            if result:
                                                return result
                                    return None

                                if 'items' in feed_tree['content']:
                                    feed_url = find_feed_url(items=feed_tree['content']['items'], target_id=feed_id)
                                    if feed_url:
                                        feed_props.feed_url = feed_url # type: ignore
                            except Exception as e:
                                logger.debug(msg=f"Error retrieving feed URL from tree: {e}")

                        # Cache the result
                        self.cache[cache_key] = feed_props
                        break
            except Exception as e:
                logger.error(msg=f"Error searching all categories for feed: {e}")

        return feed_props

    @handle_session_expiration
    def update_feed_properties(self, feed_id, title=None, category_id=None, **kwargs) -> Any:
        """Update properties for a specific feed."""
        try:
            response = self.api.update_feed_properties(
                feed_id=feed_id,
                title=title,
                category_id=category_id,
                **kwargs
            )
        except Exception as e:
            logger.error(msg=f"Error updating feed properties for feed {feed_id}: {e}")
            return None

        # Clear relevant cache entries
        if f"feed_properties_{feed_id}" in self.cache:
            del self.cache[f"feed_properties_{feed_id}"]
        self._invalidate_headline_cache()

        return response

    @handle_session_expiration
    def mark_all_read(self, feed_id, is_cat=False) -> bool:
        """Mark all articles in a feed as read, retrying if session expires."""
        try:
            # Use catchup_feed to mark all articles in a specific feed as read
            self.api.catchup_feed(feed_id=feed_id, is_cat=is_cat)
            # Invalidate relevant cache entries
            self._invalidate_headline_cache()
            return True
        except Exception as e:
            logger.error(msg=f"Error marking all articles as read: {e}")
            return False

    def _invalidate_headline_cache(self) -> None:
        """Invalidate all headline cache entries."""
        keys_to_remove: list[str] = [k for k in self.cache if k.startswith("headlines_")]
        for key in keys_to_remove:
            del self.cache[key]

        # Also invalidate categories cache as unread counts may have changed
        if "categories" in self.cache:
            del self.cache["categories"]

        # Also invalidate feeds cache as unread counts may have changed
        keys_to_remove = [k for k in self.cache if k.startswith("feeds_")]
        for key in keys_to_remove:
            del self.cache[key]

    def clear_cache(self) -> None:
        """Clear the entire cache."""
        self.cache.clear()
