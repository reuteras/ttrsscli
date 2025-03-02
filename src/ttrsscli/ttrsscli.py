"""Command line tool to access Tiny Tiny RSS.

This module provides a text-based user interface (TUI) for accessing and reading
articles from a Tiny Tiny RSS instance using the Textual library.
"""

import argparse
import functools
import html
import logging
import os
import subprocess
import sys
import tempfile
import textwrap
import webbrowser
from collections import OrderedDict
from collections.abc import Generator
from datetime import datetime
from importlib import metadata
from pathlib import Path
from time import sleep
from typing import Any, ClassVar, Literal
from urllib.parse import ParseResult, quote, urlparse

import httpx
import toml
from bs4 import BeautifulSoup
from cleanurl import Result, cleanurl
from markdownify import markdownify
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Markdown,
    MarkdownViewer,
    ProgressBar,
    Static,
    TextArea,
)
from ttrss.client import Article, Category, Feed, Headline, TTRClient
from ttrss.exceptions import TTRNotLoggedIn
from urllib3.exceptions import NameResolutionError

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(filename="ttrsscli.log"),
    ],
)
logger: logging.Logger = logging.getLogger(name=__name__)


class LimitedSizeDict(OrderedDict):
    """A dictionary that holds at most 'max_size' items and removes the oldest when full."""

    def __init__(self, max_size: int) -> None:
        """Initialize the LimitedSizeDict.

        Args:
            max_size: Maximum number of items to store in the dictionary
        """
        self.max_size: int = max_size
        super().__init__()

    def __setitem__(self, key, value) -> None:
        """Set an item in the dictionary, removing the oldest if full.

        Args:
            key: Dictionary key
            value: Value to store
        """
        if key in self:
            self.move_to_end(key=key)
        super().__setitem__(key, value)
        if len(self) > self.max_size:
            self.popitem(last=False)


def get_conf_value(op_command: str) -> str:
    """Get the configuration value from 1Password if config starts with 'op '.

    Args:
        op_command: Configuration value or 1Password command

    Returns:
        The configuration value or the output of the 1Password command

    Raises:
        SystemExit: If the 1Password command fails
    """
    if op_command.startswith("op "):
        try:
            result: subprocess.CompletedProcess[str] = subprocess.run(
                args=op_command.split(), capture_output=True, text=True, check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as err:
            logger.error(msg=f"Error executing command '{op_command}': {err}")
            print(f"Error executing command '{op_command}': {err}")
            sys.exit(1)
        except FileNotFoundError:
            logger.error(
                msg="Error: 'op' command not found. Ensure 1Password CLI is installed and accessible."
            )
            print(
                "Error: 'op' command not found. Ensure 1Password CLI is installed and accessible."
            )
            sys.exit(1)
        except NameResolutionError:
            logger.error(msg="Error: Couldn't look up server for url.")
            print("Error: Couldn't look up server for url.")
            sys.exit(1)
    else:
        return op_command


def handle_session_expiration(api_method):
    """Decorator that retries a function call after re-authenticating if session expires.

    Args:
        api_method: The API method to wrap

    Returns:
        A wrapped function that handles session expiration
    """

    @functools.wraps(wrapped=api_method)
    def wrapper(self, *args, **kwargs) -> Any:
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                return api_method(self, *args, **kwargs)
            except ConnectionResetError as err:
                logger.warning(
                    msg=f"Connection reset: {err}. Retrying ({retry_count + 1}/{max_retries})..."
                )
                retry_count += 1
                sleep(1)

                # Re-login
                if not self.login():
                    logger.error(msg="Re-authentication failed after connection reset")
                    raise RuntimeError("Re-authentication failed") from err
            except Exception as err:
                if "NOT_LOGGED_IN" in str(object=err):
                    logger.warning(
                        msg=f"Session expired: {err}. Retrying ({retry_count + 1}/{max_retries})..."
                    )
                    retry_count += 1

                    # Re-login
                    if not self.login():
                        logger.error(
                            msg="Re-authentication failed after session expiration"
                        )
                        raise RuntimeError("Re-authentication failed") from err
                else:
                    # If it's not a session issue, just raise the exception
                    raise

        # If we've exhausted our retries
        logger.error(msg=f"Failed after {max_retries} retries")
        raise RuntimeError(f"Failed after {max_retries} retries")

    return wrapper


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

        articles: list[Article] = self.api.get_articles(article_id=article_id)
        self.cache[cache_key] = articles
        return articles

    @handle_session_expiration
    def get_categories(self) -> list[Category]:
        """Fetch category list, retrying if session expires."""
        cache_key = "categories"
        if cache_key in self.cache:
            return self.cache[cache_key]

        categories: list[Category] = self.api.get_categories()
        self.cache[cache_key] = categories
        return categories

    @handle_session_expiration
    def get_feeds(self, cat_id, unread_only) -> list[Feed]:
        """Fetch feed list, retrying if session expires."""
        cache_key: str = f"feeds_{cat_id}_{unread_only}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        feeds: list[Feed] = self.api.get_feeds(cat_id=cat_id, unread_only=unread_only)
        self.cache[cache_key] = feeds
        return feeds

    @handle_session_expiration
    def get_headlines(self, feed_id, is_cat, view_mode) -> list[Headline]:
        """Fetch headlines for a feed, retrying if session expires."""
        cache_key: str = f"headlines_{feed_id}_{is_cat}_{view_mode}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        headlines: list[Headline] = self.api.get_headlines(
            feed_id=feed_id, is_cat=is_cat, view_mode=view_mode
        )
        self.cache[cache_key] = headlines
        return headlines

    @handle_session_expiration
    def mark_read(self, article_id) -> None:
        """Mark article as read, retrying if session expires."""
        self.api.mark_read(article_id=article_id)
        # Invalidate relevant cache entries
        self._invalidate_headline_cache()

    @handle_session_expiration
    def mark_unread(self, article_id) -> None:
        """Mark article as unread, retrying if session expires."""
        self.api.mark_unread(article_id=article_id)
        # Invalidate relevant cache entries
        self._invalidate_headline_cache()

    @handle_session_expiration
    def toggle_starred(self, article_id) -> None:
        """Toggle article starred, retrying if session expires."""
        self.api.toggle_starred(article_id=article_id)
        # Invalidate article cache
        if f"article_{article_id}" in self.cache:
            del self.cache[f"article_{article_id}"]

    @handle_session_expiration
    def toggle_unread(self, article_id) -> None:
        """Toggle article read/unread, retrying if session expires."""
        self.api.toggle_unread(article_id=article_id)
        # Invalidate relevant cache entries
        if f"article_{article_id}" in self.cache:
            del self.cache[f"article_{article_id}"]
        self._invalidate_headline_cache()

    @handle_session_expiration
    def subscribe_to_feed(self, feed_url, category_id=0, feed_title=None, login=None, password=None) -> Any:
        """Subscribe to a new feed."""
        response = self.api.subscribe(
            feed_url=feed_url,
            category_id=category_id,
            feed_title=feed_title,
            login=login,
            password=password
        )

        # Clear relevant cache entries
        self._invalidate_headline_cache()

        return response

    @handle_session_expiration
    def unsubscribe_feed(self, feed_id) -> Any:
        """Unsubscribe from a feed (delete it)."""
        response = self.api.unsubscribe(feed_id=feed_id)

        # Clear relevant cache entries
        self._invalidate_headline_cache()

        return response

    # Modify this method in the TTRSSClient class in ttrsscli.py
    @handle_session_expiration
    def get_feed_properties(self, feed_id) -> Any:  # noqa: PLR0912
        """Get properties for a specific feed."""
        cache_key: str = f"feed_properties_{feed_id}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        # Try to get feed properties directly
        feed_props = self.api.get_feed_properties(feed_id=feed_id)
        
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
                        if not hasattr(feed_props, 'feed_url') or not feed_props.feed_url:
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
                                        feed_props.feed_url = feed_url
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
        response = self.api.update_feed_properties(
            feed_id=feed_id,
            title=title,
            category_id=category_id,
            **kwargs
        )

        # Clear relevant cache entries
        if f"feed_properties_{feed_id}" in self.cache:
            del self.cache[f"feed_properties_{feed_id}"]
        self._invalidate_headline_cache()

        return response

    def _invalidate_headline_cache(self) -> None:
        """Invalidate all headline cache entries."""
        keys_to_remove = [k for k in self.cache if k.startswith("headlines_")]
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


class Configuration:
    """A class to handle configuration values."""

    def __init__(self, arguments) -> None:
        """Initialize the configuration.

        Args:
            arguments: Command line arguments
        """
        # Use argparse to add arguments
        arg_parser = argparse.ArgumentParser(
            description="A Textual app to access and read articles from Tiny Tiny RSS."
        )
        arg_parser.add_argument(
            "--config",
            dest="config",
            help="Path to the config file",
            default="config.toml",
        )
        arg_parser.add_argument(
            "--version",
            action="store_true",
            dest="version",
            help="Show version and exit",
            default=False,
        )
        arg_parser.add_argument(
            "--debug",
            action="store_true",
            dest="debug",
            help="Enable debug logging",
            default=False,
        )
        args: argparse.Namespace = arg_parser.parse_args(args=arguments)

        if args.debug:
            logger.setLevel(level=logging.DEBUG)
            logger.debug(msg="Debug mode enabled")

        if args.version:
            try:
                version: str = metadata.version(distribution_name="ttrsscli")
                print(f"ttrsscli version: {version}")
                sys.exit(0)
            except Exception as e:
                print(f"Error getting version: {e}")
                sys.exit(1)

        self.config: dict[str, Any] = self.load_config_file(config_file=args.config)
        try:
            self.api_url: str = get_conf_value(
                op_command=self.config["ttrss"].get("api_url", "")
            )
            self.username: str = get_conf_value(
                op_command=self.config["ttrss"].get("username", "")
            )
            self.password: str = get_conf_value(
                op_command=self.config["ttrss"].get("password", "")
            )

            # Get general settings with defaults
            general_config = self.config.get("general", {})
            self.download_folder: Path = Path(
                get_conf_value(
                    op_command=general_config.get(
                        "download_folder", os.path.expanduser(path="~/Downloads")
                    )
                )
            )
            self.auto_mark_read: bool = general_config.get("auto_mark_read", True)
            self.cache_size: int = general_config.get("cache_size", 10000)
            self.default_theme: str = general_config.get("default_theme", "dark")

            # Get readwise settings
            readwise_config = self.config.get("readwise", {})
            self.readwise_token: str = get_conf_value(
                op_command=readwise_config.get("token", "")
            )

            # Get obsidian settings
            obsidian_config = self.config.get("obsidian", {})
            self.obsidian_vault: str = get_conf_value(
                op_command=obsidian_config.get("vault", "")
            )
            self.obsidian_folder: str = get_conf_value(
                op_command=obsidian_config.get("folder", "")
            )
            self.obsidian_default_tag: str = get_conf_value(
                op_command=obsidian_config.get("default_tag", "")
            )
            self.obsidian_include_tags: bool = obsidian_config.get(
                "include_tags", False
            )
            self.obsidian_include_labels: bool = obsidian_config.get(
                "include_labels", True
            )
            self.obsidian_template: str = get_conf_value(
                op_command=obsidian_config.get("template", "")
            )

            # Make sure download folder exists
            self.download_folder.mkdir(parents=True, exist_ok=True)

            self.version: str = metadata.version(distribution_name="ttrsscli")
        except KeyError as err:
            logger.error(msg=f"Error reading configuration: {err}")
            print(f"Error reading configuration: {err}")
            sys.exit(1)

    def load_config_file(self, config_file: str) -> dict[str, Any]:
        """Load the configuration from the TOML file.

        Args:
            config_file: Path to the config file

        Returns:
            Configuration dictionary

        Raises:
            SystemExit: If the config file cannot be read
        """
        config_path = Path(config_file)
        default_config_path = Path("config.toml-default")

        try:
            if not config_path.exists():
                # If config file doesn't exist, try to use default config
                if default_config_path.exists():
                    print(
                        f"Config file {config_file} not found. Creating from default."
                    )
                    config_path.write_text(data=default_config_path.read_text())
                    print(
                        f"Created {config_file} from default. Please edit it with your settings."
                    )
                else:
                    print(f"Neither {config_file} nor {default_config_path} found.")
                    sys.exit(1)

            return toml.loads(s=config_path.read_text())
        except (FileNotFoundError, toml.TomlDecodeError) as err:
            logger.error(msg=f"Error reading configuration file: {err}")
            print(f"Error reading configuration file: {err}")
            sys.exit(1)


# Shared constants
ALLOW_IN_FULL_SCREEN: list[str] = [
    "arrow_up",
    "arrow_down",
    "page_up",
    "page_down",
    "down",
    "up",
    "right",
    "left",
    "enter",
]


class ConfirmScreen(ModalScreen):
    """Modal screen for confirming actions like deletion."""

    BINDINGS = [  # noqa: RUF012
        ("escape", "cancel", "Cancel"),
        ("enter", "confirm", "Confirm"),
    ]

    def __init__(
        self, title="Confirm", message="Are you sure?", on_confirm=None
    ) -> None:
        """Initialize the confirmation screen.

        Args:
            title: Title of the confirmation dialog
            message: Message to display
            on_confirm: Callback function to run on confirmation
        """
        super().__init__()
        self.dialog_title: str = title
        self.message: str = message
        self.on_confirm = on_confirm

    def compose(self) -> ComposeResult:
        """Define the content layout of the confirmation screen."""
        with Container(id="confirm-container"):
            yield Label(renderable=self.dialog_title, id="confirm-title")
            yield Label(renderable=self.message, id="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button(label="Confirm", id="confirm-button", variant="error")
                yield Button(label="Cancel", id="cancel-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "confirm-button":
            self.action_confirm()
        elif event.button.id == "cancel-button":
            self.action_cancel()

    def action_confirm(self) -> None:
        """Confirm the action and call the callback."""
        # Pop this screen first
        self.app.pop_screen()

        # Call the callback if provided
        if self.on_confirm:
            self.on_confirm()

    def action_cancel(self) -> None:
        """Cancel the action."""
        self.app.pop_screen()


class AddFeedScreen(ModalScreen):
    """Modal screen for adding a new feed."""

    BINDINGS = [  # noqa: RUF012
        ("escape", "close_screen", "Close"),
        ("enter", "add_feed", "Add Feed"),
    ]

    def __init__(self, client, category_id=0) -> None:
        """Initialize the add feed screen.

        Args:
            client: TTRSS client
            category_id: Optional category ID to add the feed to
        """
        super().__init__()
        self.client = client
        self.category_id: int = category_id
        self.feed_url: str  = ""
        self.feed_name:str = ""
        self.login_user:str = ""
        self.login_pass:str = ""
        self.categories: list[tuple[str, str]] = [("", "")]
        self.selected_category: int = category_id
        self._loading = False

    def compose(self) -> ComposeResult:
        """Define the content layout of the add feed screen."""
        with Container(id="feed-container"):
            yield Label(renderable="Add New Feed", id="feed-title")
            yield Input(placeholder="Feed URL (required)", id="feed-url-input")
            yield Input(placeholder="Feed Title (optional)", id="feed-title-input")
            yield Input(
                placeholder="Login username (if required)", id="login-user-input"
            )
            yield Input(
                password=True,
                placeholder="Login password (if required)",
                id="login-pass-input",
            )

            # Category selection dropdown
            yield Label(renderable="Category:")
            yield ListView(id="category-list")

            # Progress indicator (hidden initially via CSS)
            with Vertical(id="progress-container"):
                yield ProgressBar(total=100, id="add-progress-bar")

            with Horizontal(id="feed-buttons"):
                yield Button(label="Add Feed", id="add-button")
                yield Button(label="Cancel", id="cancel-button")

    def on_mount(self) -> None:
        """Set initial visibility and fetch categories."""
        # Hide progress bar initially
        progress_container: Vertical = self.query_one(selector="#progress-container", expect_type=Vertical)
        progress_container.styles.display = "none"

        # Fetch categories
        self._fetch_categories()

    def _fetch_categories(self) -> None:
        """Fetch categories for the dropdown."""
        try:
            # Fetch categories for the dropdown
            categories = self.client.get_categories()
            category_list: ListView = self.query_one(selector="#category-list", expect_type=ListView)

            for category in sorted(categories, key=lambda x: x.title):
                if category.title != "Special":  # Skip special category
                    item = ListItem(Label(renderable=category.title), id=f"cat_{category.id}")
                    category_list.append(item=item)
                    self.categories.append((category.id, category.title))

            # Select the provided category if any
            if self.category_id is not None:
                for i, (cat_id, _) in enumerate(iterable=self.categories):
                    if cat_id == self.category_id:
                        category_list.index = i
                        break
        except Exception as e:
            self.notify(
                title="Error",
                message=f"Failed to load categories: {e}",
                severity="error",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "add-button":
            self.action_add_feed()
        elif event.button.id == "cancel-button":
            self.action_close_screen()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update variables when input changes."""
        if event.input.id == "feed-url-input":
            self.feed_url = event.value
        elif event.input.id == "feed-title-input":
            self.feed_name = event.value
        elif event.input.id == "login-user-input":
            self.login_user = event.value
        elif event.input.id == "login-pass-input":
            self.login_pass = event.value

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle category selection."""
        if event.list_view.id == "category-list" and event.list_view.index is not None:
            try:
                self.selected_category = int(self.categories[event.list_view.index][0])
            except IndexError:
                # Handle case when the index is out of range
                pass

    def action_add_feed(self) -> None:
        """Add a new feed with the provided details."""
        if not self.feed_url:
            self.notify(
                message="Please enter a feed URL",
                title="Required Field",
                severity="warning",
            )
            return

        try:
            # Show progress indicator
            progress_container: Vertical = self.query_one(selector="#progress-container", expect_type=Vertical)
            progress_container.styles.display = "block"
            self._loading = True

            # Prepare authentication if provided
            auth_login: str | None = self.login_user if self.login_user else None
            auth_pass: str | None = self.login_pass if self.login_pass else None

            # Add the feed
            result = self.client.subscribe_to_feed(
                feed_url=self.feed_url,
                category_id=self.selected_category,
                feed_title=self.feed_name if self.feed_name else None,
                login=auth_login,
                password=auth_pass,
            )

            # Hide progress indicator
            progress_container.styles.display = "none"
            self._loading = False

            if result and hasattr(result, "status") and result.status:
                self.notify(message="Feed added successfully", title="Success")
                self.dismiss(result=True)
            else:
                error_msg = (
                    getattr(result, "message", "Unknown error")
                    if result
                    else "Unknown error"
                )
                self.notify(
                    message=f"Failed to add feed: {error_msg}",
                    title="Error",
                    severity="error",
                )
        except Exception as e:
            # Hide progress indicator if there's an error
            if self._loading:
                progress_container = self.query_one(selector="#progress-container", expect_type=Vertical)
                progress_container.styles.display = "none"
                self._loading = False

            logger.error(msg=f"Error adding feed: {e}")
            self.notify(
                message=f"Error adding feed: {e}", title="Error", severity="error"
            )

    def action_close_screen(self) -> None:
        """Close the screen."""
        self.dismiss(result=False)


class EditFeedScreen(ModalScreen):
    """Modal screen for editing feed properties."""

    BINDINGS = [  # noqa: RUF012
        ("escape", "close_screen", "Close"),
        ("enter", "save_feed", "Save"),
        ("delete", "delete_feed", "Delete Feed"),
    ]

    def __init__(self, client, feed_id, title="", url="") -> None:
        """Initialize the edit feed screen.

        Args:
            client: TTRSS client
            feed_id: Feed ID to edit
            title: Current feed title
            url: Current feed URL
        """
        super().__init__()
        self.client = client
        self.feed_id = feed_id
        self.current_title: str = title
        self.current_url: str = url
        self.feed_title: str = title
        self.categories: list[str] = []
        self.selected_category = None
        self.current_category_id = None
        self.feed_details = None
        self._loading = False

    def compose(self) -> ComposeResult:
        """Define the content layout of the edit feed screen."""
        with Container(id="feed-container"):
            yield Label(renderable="Edit Feed", id="feed-title")
            yield Input(
                placeholder="Feed Title",
                id="feed-title-input",
                value=self.current_title,
            )

            # Feed URL (disabled, for display only)
            yield Label(renderable="Feed URL:")
            yield Input(
                placeholder="Feed URL",
                id="feed-url-input",
                value=self.current_url,
                disabled=True,
            )

            # Category selection dropdown
            yield Label(renderable="Category:")
            yield ListView(id="category-list")

            # Feed settings
            yield Label(renderable="Settings:")

            with Vertical(id="settings-container"):
                yield Static(content="Loading feed settings...")

            # Progress indicator (hidden using display property)
            with Vertical(id="progress-container"):
                yield ProgressBar(total=100, id="edit-progress-bar")

            with Horizontal(id="feed-buttons"):
                yield Button(label="Save Changes", id="save-button", variant="primary")
                yield Button(label="Cancel", id="cancel-button")
                yield Button(label="Delete Feed", id="delete-button", variant="error")

    def on_mount(self) -> None:
        """Set initial visibility of progress bar."""
        # Hide progress bar initially
        progress_container: Vertical = self.query_one(selector="#progress-container", expect_type=Vertical)
        progress_container.styles.display = "none"

    async def on_show(self) -> None:  # noqa: PLR0912, PLR0915
        """Fetch categories and feed details when screen is shown."""
        try:
            # Show progress indicator
            self._loading = True
            progress_container: Vertical = self.query_one(selector="#progress-container", expect_type=Vertical)
            progress_container.styles.display = "block"

            # Fetch categories for the dropdown
            categories = self.client.get_categories()
            category_list: ListView = self.query_one(selector="#category-list", expect_type=ListView)

            for category in sorted(categories, key=lambda x: x.title):
                if category.title != "Special":  # Skip special category
                    item = ListItem(Label(renderable=category.title), id=f"cat_{category.id}")
                    category_list.append(item=item)
                    self.categories.append((category.id, category.title)) # type: ignore

            # Fetch feed details using get_feed_properties with additional error handling
            try:
                self.feed_details = self.client.get_feed_properties(feed_id=self.feed_id)

                # Update feed URL if available in feed_details
                if self.feed_details:
                    # Update the URL field if feed_url is available
                    if hasattr(self.feed_details, "feed_url") and self.feed_details.feed_url:
                        self.current_url = self.feed_details.feed_url
                        url_input: Input = self.query_one(selector="#feed-url-input", expect_type=Input)
                        url_input.value = self.current_url
                    elif self.current_url:  # Use the URL provided during initialization if available
                        url_input = self.query_one(selector="#feed-url-input", expect_type=Input)
                        url_input.value = self.current_url
                    else:
                        # Notify that URL couldn't be retrieved
                        self.notify(
                            title="Warning",
                            message="Could not retrieve feed URL. This field will be display-only.",
                            severity="warning",
                            timeout=5)

                if not self.feed_details:
                    # If get_feed_properties returns None, try to get feed info from all feeds
                    logger.info(msg=f"Trying to find feed {self.feed_id} in all feeds")
                    all_feeds = []
                    for category in categories:
                        try:
                            feeds = self.client.get_feeds(cat_id=category.id, unread_only=False)
                            all_feeds.extend(feeds)
                        except Exception as feed_err:
                            logger.warning(msg=f"Error getting feeds for category {category.id}: {feed_err}")

                    # Find the feed in all_feeds
                    for feed in all_feeds:
                        if int(feed.id) == int(self.feed_id):
                            self.feed_details = feed
                            # Check for feed URL
                            if hasattr(feed, "feed_url") and feed.feed_url:
                                self.current_url = feed.feed_url
                                url_input = self.query_one(selector="#feed-url-input", expect_type=Input)
                                url_input.value = self.current_url
                            break
            except Exception as feed_error:
                logger.error(msg=f"Error fetching feed details: {feed_error}")
                self.notify(
                    title="Warning",
                    message="Could not fetch complete feed details. Some settings may not be available.",
                    severity="warning",
                    timeout=5
                )
                # Create minimal feed details with the information we have
                self.feed_details = type('obj', (object,), {
                    'title': self.current_title,
                    'cat_id': 0,  # Default to uncategorized
                    'update_enabled': True,
                    'include_in_digest': True,
                    'always_display_attachments': False,
                    'mark_unread_on_update': False
                })

            if self.feed_details:
                # Update feed values from details
                if hasattr(self.feed_details, "title"):
                    self.current_title = self.feed_details.title # type: ignore
                    self.feed_title = self.feed_details.title # type: ignore
                    title_input: Input = self.query_one(selector="#feed-title-input", expect_type=Input)
                    title_input.value = self.current_title

                # Get current category
                if hasattr(self.feed_details, "cat_id"):
                    self.current_category_id = self.feed_details.cat_id # type: ignore

                    # Select the current category in the list
                    for i, (cat_id, _) in enumerate(self.categories):
                        if int(cat_id) == int(self.current_category_id):
                            category_list.index = i
                            self.selected_category = cat_id
                            break

                # Display feed settings
                settings_container = self.query_one("#settings-container", Vertical)
                # Remove previous children
                await settings_container.remove_children()

                # Add toggles for common feed settings
                settings = [
                    (
                        "update-enabled",
                        "Enable Updates",
                        getattr(self.feed_details, "update_enabled", True),
                    ),
                    (
                        "include-in-digest",
                        "Include in Digest",
                        getattr(self.feed_details, "include_in_digest", True),
                    ),
                    (
                        "always-display-attachments",
                        "Always Display Attachments",
                        getattr(self.feed_details, "always_display_attachments", False),
                    ),
                    (
                        "mark-unread-on-update",
                        "Mark Unread on Update",
                        getattr(self.feed_details, "mark_unread_on_update", False),
                    ),
                ]

                # First create all the widgets that will go in the settings container
                setting_widgets = []
                for setting_id, label_text, value in settings:
                    # Create a horizontal container for each setting with its checkbox and label
                    container = Horizontal(id=f"setting-{setting_id}")
                    # Add the checkbox and label as its children in the constructor
                    container.compose_add_child(Checkbox(value=value, id=f"checkbox-{setting_id}"))
                    container.compose_add_child(Label(label_text))
                    # Add to our list of widgets to mount
                    setting_widgets.append(container)

                # Now mount all the widgets at once
                if setting_widgets:
                    await settings_container.mount(*setting_widgets)

            # Hide progress indicator
            progress_container.styles.display = "none"
            self._loading = False

        except Exception as e:
            # Hide progress indicator if there's an error
            if self._loading:
                progress_container = self.query_one("#progress-container", Vertical)
                progress_container.styles.display = "none"
                self._loading = False

            logger.error(f"Error loading feed details: {e}")
            self.notify(
                title="Error",
                message=f"Failed to load feed details: {e}",
                severity="error",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "save-button":
            self.action_save_feed()
        elif event.button.id == "cancel-button":
            self.action_close_screen()
        elif event.button.id == "delete-button":
            self.action_confirm_delete()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update variables when input changes."""
        if event.input.id == "feed-title-input":
            self.feed_title = event.value

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle category selection."""
        if event.list_view.id == "category-list" and event.list_view.index is not None:
            self.selected_category = self.categories[event.list_view.index][0]

    def action_save_feed(self) -> None:
        """Save the feed with updated properties."""
        try:
            # Show progress indicator
            progress_container = self.query_one("#progress-container", Vertical)
            progress_container.styles.display = "block"
            self._loading = True

            # Collect settings from checkboxes
            settings = {}
            for setting_id in [
                "update-enabled",
                "include-in-digest",
                "always-display-attachments",
                "mark-unread-on-update",
            ]:
                checkbox = self.query_one(f"#checkbox-{setting_id}", Checkbox)
                settings[setting_id.replace("-", "_")] = checkbox.value

            # Update the feed
            result = self.client.update_feed_properties(
                feed_id=self.feed_id,
                title=self.feed_title,
                category_id=self.selected_category,
                **settings,
            )

            # Hide progress indicator
            progress_container.styles.display = "none"
            self._loading = False

            if result and getattr(result, "status", False):
                self.notify(message="Feed updated successfully", title="Success")
                self.dismiss(result=True)
            else:
                self.notify(
                    message=f"Failed to update feed: {getattr(result, 'message', 'Unknown error')}",
                    title="Error",
                    severity="error",
                )
        except Exception as e:
            # Hide progress indicator if there's an error
            if self._loading:
                progress_container = self.query_one("#progress-container", Vertical)
                progress_container.styles.display = "none"
                self._loading = False

            logger.error(msg=f"Error updating feed: {e}")
            self.notify(
                message=f"Error updating feed: {e}", title="Error", severity="error"
            )

    def action_confirm_delete(self) -> None:
        """Show confirmation dialog before deleting feed."""
        # We'll show a simple confirm dialog within this screen
        # instead of pushing a new screen
        self.app.push_screen(
            ConfirmScreen(
                title="Delete Feed",
                message=f"Are you sure you want to delete the feed '{self.current_title}'?",
                on_confirm=self.delete_feed,
            )
        )

    def delete_feed(self) -> None:
        """Delete the feed after confirmation."""
        try:
            # Show progress indicator
            progress_container = self.query_one("#progress-container", Vertical)
            progress_container.styles.display = "block"
            self._loading = True

            # Delete the feed
            result = self.client.unsubscribe_feed(feed_id=self.feed_id)

            # Hide progress indicator
            progress_container.styles.display = "none"
            self._loading = False

            if result and getattr(result, "status", False):
                self.notify(message="Feed deleted successfully", title="Success")
                self.dismiss(result={"action": "deleted", "feed_id": self.feed_id})
            else:
                self.notify(
                    message=f"Failed to delete feed: {getattr(result, 'message', 'Unknown error')}",
                    title="Error",
                    severity="error",
                )
        except Exception as e:
            # Hide progress indicator if there's an error
            if self._loading:
                progress_container = self.query_one("#progress-container", Vertical)
                progress_container.styles.display = "none"
                self._loading = False

            logger.error(msg=f"Error deleting feed: {e}")
            self.notify(
                message=f"Error deleting feed: {e}", title="Error", severity="error"
            )

    def action_close_screen(self) -> None:
        """Close the screen."""
        self.dismiss(result=False)


# Textual Screen classes
class SearchScreen(ModalScreen):
    """Modal screen for searching articles."""

    BINDINGS = [  # noqa: RUF012
        ("escape", "close_screen", "Close"),
        ("enter", "search", "Search"),
    ]

    def __init__(self) -> None:
        """Initialize the search screen."""
        super().__init__()
        self.search_term: str = ""

    def compose(self) -> ComposeResult:
        """Define the content layout of the search screen."""
        with Container(id="search-container"):
            yield Label(renderable="Search Articles", id="search-title")
            yield Input(placeholder="Enter search term...", id="search-input")
            with Horizontal(id="search-buttons"):
                yield Button(label="Search", id="search-button")
                yield Button(label="Cancel", id="cancel-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "search-button":
            self.action_search()
        elif event.button.id == "cancel-button":
            self.action_close_screen()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update search term when input changes."""
        self.search_term = event.value

    def action_search(self) -> None:
        """Search for articles with the current search term."""
        if self.search_term:
            self.dismiss(result=self.search_term)
        else:
            self.notify(message="Please enter a search term", title="Search")

    def action_close_screen(self) -> None:
        """Close the search screen."""
        self.dismiss(None)


class LinkSelectionScreen(ModalScreen):
    """Modal screen to show extracted links and allow selection."""

    BINDINGS = [  # noqa: RUF012
        ("escape", "cancel", "Cancel"),
        ("enter", "select", "Select"),
    ]

    def __init__(self, configuration, links, open_links="browser", open=False) -> None:
        """Initialize the link selection screen.

        Args:
            configuration: App configuration
            links: List of tuples with link title and URL
            open_links: Action to perform on selected link
            open: Whether to open the link after saving to Readwise
        """
        super().__init__()
        self.links: Any = links or []  # Ensure links is never None
        self.open_links: str = open_links
        self.open: bool = open
        self.configuration: Configuration = configuration
        self.selected_index = 0
        self.http_client = httpx.Client(follow_redirects=True)

    def compose(self) -> ComposeResult:
        """Define the content layout of the link selection screen."""
        if self.open_links == "browser":
            title = "Select a link to open (ESC to go back):"
        elif self.open_links == "download":
            title = "Select a link to download (ESC to go back):"
        elif self.open_links == "readwise":
            title = "Select a link to save to Readwise (ESC to go back):"
        else:
            title = "Select a link (ESC to go back):"

        yield Label(renderable=title)

        # Handle empty links list
        if not self.links:
            yield Label(renderable="No links found in article")
            return

        # Create a list view with all links
        link_select = ListView(
            *[
                ListItem(Label(renderable=self._format_link_item(link=link)))
                for link in self.links
            ],
            id="link-list",
        )

        # Calculate width based on longest link
        longest_link: int = (
            max(len(self._format_link_item(link)) for link in self.links)
            if self.links
            else 40
        )

        link_select.styles.align_horizontal = "left"
        link_select.styles.width = min(longest_link + 6, 120)
        link_select.styles.max_width = "100%"
        yield link_select

    def on_mount(self) -> None:
        """Set focus to the list view when screen is mounted."""
        link_list: ListView = self.query_one(
            selector="#link-list", expect_type=ListView
        )
        link_list.focus()

    def _format_link_item(self, link: tuple) -> str:
        """Format a link for display in the list.

        Args:
            link: Tuple of (title, url)

        Returns:
            Formatted link string
        """
        title, url = link

        # Ensure neither value is None
        title = title or "No title"
        url = url or "No URL"

        # Truncate long titles and URLs for better display
        max_line_length = 80

        if len(title) > max_line_length:
            title = title[: max_line_length - 3] + "..."

        if len(url) > max_line_length:
            # Try to keep the domain and part of the path
            try:
                parsed: ParseResult = urlparse(url=url)
                domain: str = parsed.netloc
                path: str = parsed.path

                if len(domain) + 10 >= max_line_length:  # If domain itself is very long
                    url: str = domain[: max_line_length - 3] + "..."
                else:
                    # Keep domain and truncate path
                    path_max: int = max_line_length - len(domain) - 10
                    path_truncated: str = (
                        path[:path_max] + "..." if len(path) > path_max else path
                    )
                    url = f"{domain}{path_truncated}"
            except Exception:
                # Fall back to simple truncation if URL parsing fails
                url = url[: max_line_length - 3] + "..."

        return f"{title}\n{url}"

    def action_cancel(self) -> None:
        """Close the screen without taking action."""
        self.app.pop_screen()

    def action_select(self) -> None:
        """Process the selected link."""
        link_list: ListView = self.query_one(
            selector="#link-list", expect_type=ListView
        )
        if link_list.index is None or not self.links:
            self.notify(
                title="Error", message="No link selected", timeout=3, severity="error"
            )
            self.app.pop_screen()
            return

        try:
            index: int = link_list.index
            if index < 0 or index >= len(self.links):
                self.notify(
                    title="Error",
                    message="Invalid selection",
                    timeout=3,
                    severity="error",
                )
                self.app.pop_screen()
                return

            link = self.links[index][1]
            if not link:
                self.notify(
                    title="Error",
                    message="Selected link has no URL",
                    timeout=3,
                    severity="error",
                )
                self.app.pop_screen()
                return

            self._process_link(link=link)
            self.app.pop_screen()
        except Exception as e:
            logger.error(msg=f"Error processing selection: {e}")
            self.notify(
                title="Error", message=f"Error: {e!s}", timeout=3, severity="error"
            )
            self.app.pop_screen()

    def _process_link(self, link: str) -> None:
        """Process the selected link based on open_links setting.

        Args:
            link: The URL to process
        """
        if self.open_links == "browser":
            webbrowser.open(url=link)
            self.notify(title="Opening", message="Opening link in browser", timeout=3)
        elif self.open_links == "download":
            self.download_file(link=link)
        elif self.open_links == "readwise":
            self._save_to_readwise(link=link)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle list view selection.

        Args:
            event: Selection event
        """
        try:
            # Process the selected item
            if event.list_view and len(self.links) > 0:
                index = event.list_view.index
                if index is not None and 0 <= index < len(self.links):
                    link = self.links[index][1]
                    if link:
                        self._process_link(link=link)

            # Close the screen
            self.app.pop_screen()
        except Exception as e:
            logger.error(msg=f"Error handling link selection: {e}")
            self.notify(
                title="Error", message=f"Error: {e!s}", timeout=3, severity="error"
            )
            self.app.pop_screen()

    def download_file(self, link: str) -> None:
        """Download a file from the given URL using httpx.

        Args:
            link: URL to download
        """
        try:
            # Extract filename from URL
            filename: str = Path(urlparse(url=link).path).name
            if not filename:
                filename = "downloaded_file"

            # Download the file
            download_path = self.configuration.download_folder / filename

            with self.http_client.stream(method="GET", url=link) as response:
                response.raise_for_status()
                with open(file=download_path, mode="wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)

            self.notify(
                title="Downloaded",
                message=f"File downloaded to {download_path}",
                timeout=5,
            )
        except httpx.HTTPError as e:
            logger.error(msg=f"HTTP error downloading file: {e}")
            self.notify(
                title="Download Error",
                message=f"HTTP error downloading file: {e!s}",
                timeout=5,
                severity="error",
            )
        except Exception as e:
            logger.error(msg=f"Error downloading file: {e}")
            self.notify(
                title="Download Error",
                message=f"Error downloading file: {e!s}",
                timeout=5,
                severity="error",
            )

    def _save_to_readwise(self, link: str) -> None:
        """Save the selected link to Readwise.

        Args:
            link: URL to save
        """
        try:
            os.environ["READWISE_TOKEN"] = self.configuration.readwise_token
            import readwise
            from readwise.model import PostResponse

            # Show a progress indicator during the API call
            app.push_screen(screen="progress")

            # Save to Readwise
            response: tuple[bool, PostResponse] = readwise.save_document(url=link)

            # Remove progress screen
            app.pop_screen()

            if response[1].url and response[1].id:
                self.notify(
                    title="Readwise",
                    message="Link saved to Readwise.",
                    timeout=5,
                )
                if self.open:
                    webbrowser.open(url=response[1].url)
            else:
                self.notify(
                    title="Readwise",
                    message="Error saving link to Readwise.",
                    timeout=5,
                    severity="error",
                )
        except Exception as err:
            # Make sure to remove progress screen if there's an error
            if isinstance(self.screen, ProgressScreen):
                app.pop_screen()

            logger.error(msg=f"Error saving to Readwise: {err}")
            self.notify(
                title="Readwise",
                message=f"Error: {err!s}",
                timeout=5,
                severity="error",
            )


class ProgressScreen(ModalScreen):
    """Screen that shows progress for long operations."""

    def compose(self) -> ComposeResult:
        """Define the content layout of the progress screen."""
        yield Static(content="Working...", id="progress-text")
        yield ProgressBar(total=100, id="progress-bar")


class LinkableMarkdownViewer(MarkdownViewer):
    """An extended MarkdownViewer that allows web links to be clicked."""

    @on(message_type=Markdown.LinkClicked)
    def handle_link(self, event: Markdown.LinkClicked) -> None:
        """Open links in the default web browser.

        Args:
            event: Link clicked event
        """
        if event.href:
            event.prevent_default()
            webbrowser.open(url=event.href)


class FullScreenMarkdown(Screen):
    """A full-screen Markdown viewer."""

    def __init__(self, markdown_content: str) -> None:
        """Initialize the full-screen Markdown viewer.

        Args:
            markdown_content: Markdown content to display
        """
        super().__init__()
        self.markdown_content: str = markdown_content

    def compose(self) -> Generator[LinkableMarkdownViewer, Any, None]:
        """Define the content layout of the full-screen Markdown viewer."""
        yield LinkableMarkdownViewer(
            markdown=self.markdown_content, show_table_of_contents=True
        )

    def on_key(self, event) -> None:
        """Close the full-screen Markdown viewer on any key press except navigation keys.

        Args:
            event: Key event
        """
        if event.key in ALLOW_IN_FULL_SCREEN:
            pass
        else:
            self.app.pop_screen()


class FullScreenTextArea(Screen):
    """A full-screen TextArea."""

    def __init__(self, text: str) -> None:
        """Initialize the full-screen TextArea.

        Args:
            text: Text to display
        """
        super().__init__()
        self.text: str = text

    def compose(self) -> Generator[TextArea, Any, None]:
        """Define the content layout of the full-screen TextArea."""
        yield TextArea.code_editor(text=self.text, language="markdown", read_only=True)

    def on_key(self, event) -> None:
        """Close the full-screen TextArea on any key press except navigation keys.

        Args:
            event: Key event
        """
        event.prevent_default()
        if event.key in ALLOW_IN_FULL_SCREEN:
            pass
        else:
            self.app.pop_screen()


class HelpScreen(Screen):
    """A modal help screen."""

    def compose(self) -> ComposeResult:
        """Define the content layout of the help screen."""
        yield LinkableMarkdownViewer(
            markdown="""# Help for ttrsscli
## Navigation
- **j / k / n**: Navigate articles
- **J / K**: Navigate categories
- **Arrow keys**: Up and down in current pane
- **tab / shift+tab**: Navigate panes

## General keys
- **h / ?**: Show this help
- **q**: Quit
- **G / ,**: Refresh
- **c**: Clear content in article pane
- **C**: Toggle clean URLs
- **d**: Toggle dark and light mode
- **f**: Search articles
- **v**: Show version

## Feed Management
- **a**: Add a new feed
- **E**: Edit the selected feed (also allows deletion)

## Article keys
- **H**: Toggle "header" (info) for article
- **l**: Add article to Readwise
- **L**: Add article to Readwise and open that Readwise page in browser
- **M**: View markdown source for article
- **m**: Maximize content pane (ESC to minimize)
- **r**: Toggle read/unread
- **s**: Star article
- **O**: Export markdown to Obsidian
- **o**: Open article in browser
- **ctrl+l**: Open list with links in article, selected link is sent to Readwise
- **ctrl+L**: Open list with links in article, selected link is sent to Readwise and opened in browser
- **ctrl+o**: Open list with links in article, selected link opens in browser
- **ctrl+s**: Save selected link from article to download folder

## Category and feed keys
- **e**: Toggle expand category
- **g**: Toggle group articles to feed
- **R**: Open recently read articles
- **S**: Show special categories
- **u**: Toggle show all categories (include unread)

## Links

Project home: [https://github.com/reuteras/ttrsscli](https://github.com/reuteras/ttrsscli)

For more about Tiny Tiny RSS, see the [Tiny Tiny RSS website](https://tt-rss.org/). Tiny Tiny RSS is not affiliated with this project.
""",
            id="fullscreen-content",
            show_table_of_contents=False,
            open_links=False,
        )

    def on_key(self, event) -> None:
        """Close the help screen on any key press except navigation keys."""
        event.prevent_default()
        if event.key in ALLOW_IN_FULL_SCREEN:
            pass
        else:
            self.app.pop_screen()


# Main Textual App class
class ttrsscli(App[None]):
    """A Textual app to access and read articles from Tiny Tiny RSS."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("?", "toggle_help", "Help"),
        ("a", "add_feed", "Add Feed"),
        ("C", "toggle_clean_url", "Toggle clean URLs"),
        ("c", "clear", "Clear"),
        ("comma", "refresh", "Refresh"),
        ("ctrl+l", "readwise_article_url", "Add link to Readwise"),
        (
            "ctrl+shift+l",
            "readwise_article_url_and_open",
            "Add link to Readwise and open",
        ),
        ("ctrl+o", "open_article_url", "Open article URLs"),
        ("ctrl+s", "save_article_url", "Save link to downloads"),
        ("d", "toggle_dark", "Toggle dark mode"),
        ("e", "toggle_category", "Toggle category expansion"),
        ("E", "edit_feed", "Edit Feed"),
        ("f", "search", "Search"),
        ("G", "refresh", "Refresh"),
        ("g", "toggle_feeds", "Group feeds"),
        ("H", "toggle_header", "Header"),
        ("h", "toggle_help", "Help"),
        ("J", "next_category", "Next category"),
        ("j", "next_article", "Next article"),
        ("K", "previous_category", "Previous category"),
        ("k", "previous_article", "Previous article"),
        ("l", "add_to_later_app", "Add to Readwise"),
        ("L", "add_to_later_app_and_open", "Add to Readwise and open"),
        ("M", "view_markdown_source", "View md source"),
        ("m", "maximize_content", "Maximize content"),
        ("n", "next_article", "Next article"),
        ("O", "export_to_obsidian", "Export to Obsidian"),
        ("o", "open_original_article", "Open in browser"),
        ("q", "quit", "Quit"),
        ("R", "recently_read", "Recently read"),
        ("r", "toggle_read", "Mark Read/Unread"),
        ("S", "toggle_special_categories", "Special categories"),
        ("s", "toggle_star", "Star article"),
        ("shift+tab", "focus_previous_pane", "Previous pane"),
        ("tab", "focus_next_pane", "Next pane"),
        ("u", "toggle_unread", "Toggle unread only"),
        ("v", "show_version", "Show version"),
    ]
    SCREENS: ClassVar[dict[str, type[Screen]]] = {
        "help": HelpScreen,
        "search": SearchScreen,
        "progress": ProgressScreen,
        "add_feed": AddFeedScreen,
        "edit_feed": EditFeedScreen,
        "confirm": ConfirmScreen,
    }
    CSS_PATH: str = "styles.tcss"

    def __init__(self) -> None:
        """Connect to Tiny Tiny RSS and initialize the app."""
        super().__init__()  # Initialize first for early access to notify/etc.

        try:
            # Load the configuration via the Configuration class sending it command line arguments
            self.configuration = Configuration(arguments=sys.argv[1:])

            # Set theme based on configuration
            self.theme = (
                "textual-dark"
                if self.configuration.default_theme == "dark"
                else "textual-light"
            )

            # Try to connect to TT-RSS
            self.client = TTRSSClient(
                url=self.configuration.api_url,
                username=self.configuration.username,
                password=self.configuration.password,
            )
        except TTRNotLoggedIn:
            logger.error(
                msg="Could not log in to Tiny Tiny RSS. Check your credentials."
            )
            print("Error: Could not log in to Tiny Tiny RSS. Check your credentials.")
            sys.exit(1)
        except NameResolutionError:
            logger.error(msg="Couldn't look up server for url.")
            print("Error: Couldn't look up server for url.")
            sys.exit(1)
        except Exception as e:
            logger.error(msg=f"Unexpected error: {e}")
            print(f"Error: {e}")
            sys.exit(1)

        self.START_TEXT: str = (
            "# Welcome to ttrsscli!\n\n"
            "A text-based interface for Tiny Tiny RSS.\n\n"
            "## Quick Start\n\n"
            "- Use **Tab** and **Shift+Tab** to navigate between panes\n"
            "- Press **?** for help\n"
            "- Select a category to see articles\n"
            "- Select an article to read its content\n"
        )

        # State variables
        self.article_id: int = 0
        self.category_id = None
        self.category_index: int = 0
        self.clean_url: bool = True
        self.content_markdown: str = self.START_TEXT
        self.current_article: Article | None = None
        self.current_article_title: str = ""
        self.current_article_url: str = ""
        self.current_article_urls: list[tuple[str, str]] = []
        self.expand_category: bool = False
        self.first_view: bool = True
        self.group_feeds: bool = True
        self.is_loading: bool = False
        self.last_key: str = ""
        self.selected_article_ids: set[int] = set()  # Track which articles are selected
        self.show_header: bool = False
        self.show_unread_only = reactive(default=True)
        self.show_special_categories: bool = False
        self.tags = LimitedSizeDict(max_size=self.configuration.cache_size)
        self.temp_files: list[Path] = []  # List of temporary files to clean up on exit

        # Create httpx client for downloads
        self.http_client = httpx.Client(follow_redirects=True)

    def compose(self) -> ComposeResult:
        """Compose the three pane layout."""
        yield Header(show_clock=True, name=f"ttrsscli v{self.configuration.version}")
        with Horizontal():
            yield ListView(id="categories")
            with Vertical():
                yield ListView(id="articles")
                yield LinkableMarkdownViewer(
                    id="content", show_table_of_contents=False, markdown=self.START_TEXT
                )
        yield Footer()

    async def on_list_view_highlighted(self, message: Message) -> None:
        """Called when an item is highlighted in the ListViews."""
        # Skip handling if we're in a modal screen
        if isinstance(self.screen, ModalScreen):
            return

        highlighted_item: Any = message.item  # type: ignore
        try:
            if highlighted_item is not None:
                # Handle category selection -> refresh articles
                if (
                    hasattr(highlighted_item, "id")
                    and not highlighted_item.id is None
                    and highlighted_item.id.startswith("cat_")
                ):
                    category_id = int(highlighted_item.id.replace("cat_", ""))
                    self.category_id = highlighted_item.id
                    await self.refresh_articles(show_id=category_id)
                    # Update category index position for navigation
                    if hasattr(highlighted_item, "parent") and hasattr(
                        highlighted_item.parent, "index"
                    ):
                        self.category_index = highlighted_item.parent.index

                # Handle feed selection in expanded category view -> refresh articles
                elif (
                    hasattr(highlighted_item, "id")
                    and not highlighted_item.id is None
                    and highlighted_item.id.startswith("feed_")
                ):
                    await self.refresh_articles(show_id=highlighted_item.id)

                # Handle feed title selection in article list -> navigate articles
                elif (
                    hasattr(highlighted_item, "id")
                    and not highlighted_item.id is None
                    and highlighted_item.id.startswith("ft_")
                ):
                    if self.last_key == "j":
                        self.action_next_article()
                    elif self.last_key == "k":
                        if highlighted_item.parent.index == 0:
                            self.action_next_article()
                        else:
                            self.action_previous_article()

                # Handle article selection -> display selected article content
                elif (
                    hasattr(highlighted_item, "id")
                    and not highlighted_item.id is None
                    and highlighted_item.id.startswith("art_")
                ):
                    article_id = int(highlighted_item.id.replace("art_", ""))
                    self.article_id = article_id
                    highlighted_item.styles.text_style = "none"
                    self.selected_article_ids.add(article_id)
                    await self.display_article_content(article_id=article_id)
        except Exception as err:
            logger.error(msg=f"Error handling list view highlight: {err}")
            self.notify(message=f"Error: {err}", title="Error", severity="error")

    async def on_list_view_selected(self, message: Message) -> None:
        """Called when an item is selected in the ListView."""
        # Skip handling if we're in a modal screen
        if isinstance(self.screen, ModalScreen):
            return

        selected_item: Any = message.item  # type: ignore

        try:
            if selected_item:
                # Handle category selection
                if (
                    hasattr(selected_item, "id")
                    and not selected_item.id is None
                    and selected_item.id.startswith("cat_")
                ):
                    category_id = int(selected_item.id.replace("cat_", ""))
                    await self.refresh_articles(show_id=category_id)
                    self.action_focus_next_pane()

                # Handle article selection
                elif (
                    hasattr(selected_item, "id")
                    and not selected_item.id is None
                    and selected_item.id.startswith("art_")
                ):
                    article_id = int(selected_item.id.replace("art_", ""))
                    self.article_id = article_id
                    selected_item.styles.text_style = "none"
                    self.selected_article_ids.add(article_id)
                    await self.display_article_content(article_id=article_id)
        except Exception as err:
            logger.error(msg=f"Error handling list view selection: {err}")
            self.notify(message=f"Error: {err}", title="Error", severity="error")

    async def on_mount(self) -> None:
        """Fetch and display categories on startup."""
        await self.refresh_categories()
        await self.refresh_articles()

    @work
    async def action_add_feed(self) -> None:
        """Open screen to add a new feed."""
        try:
            # Determine if a category is selected
            category_id: int = 0
            if (
                hasattr(self, "category_id")
                and self.category_id
                and self.category_id.startswith("cat_")
            ):
                category_id = int(self.category_id.replace("cat_", ""))

            # Create the add feed screen
            add_feed_screen = AddFeedScreen(client=self.client, category_id=category_id)

            # Push the screen and wait for result
            result = await self.push_screen_wait(screen=add_feed_screen)

            # Refresh if a feed was added
            if result:
                self.notify(message="Refreshing after adding feed...", title="Refresh")
                await self.refresh_categories()
                await self.refresh_articles()
        except Exception as e:
            logger.error(msg=f"Error in add feed action: {e}")
            self.notify(
                message=f"Error adding feed: {e}", title="Error", severity="error"
            )

    @work
    async def action_edit_feed(self) -> None:
        """Open screen to edit the selected feed."""
        # Check if a feed is selected
        feed_id = None
        feed_title: str = ""
        feed_url: str = ""

        # Check if we're in the categories view with a feed selected
        if (
            hasattr(self, "category_id")
            and self.category_id
            and self.category_id.startswith("feed_")
        ):
            feed_id = int(self.category_id.replace("feed_", ""))

            # Try to get feed details
            for category in self.client.get_categories():
                for feed in self.client.get_feeds(
                    cat_id=category.id, unread_only=False  # type: ignore
                ):
                    if feed.id == feed_id:  # type: ignore
                        feed_title = feed.title  # type: ignore
                        feed_url = getattr(feed, "feed_url", "")
                        break

        # Or check if we have an article selected - use its feed info
        elif self.current_article:
            feed_id = getattr(self.current_article, "feed_id", None)
            feed_title = getattr(self.current_article, "feed_title", "")

        if not feed_id:
            self.notify(
                message="Please select a feed to edit",
                title="Edit Feed",
                severity="warning",
            )
            return

        # Create and push the edit feed screen
        edit_feed_screen = EditFeedScreen(
            client=self.client, feed_id=feed_id, title=feed_title, url=feed_url
        )
        result = await self.push_screen_wait(screen=edit_feed_screen)

        # Refresh if feed was updated or deleted
        if result:
            self.notify(message="Refreshing after feed update...", title="Refresh")
            await self.refresh_categories()
            await self.refresh_articles()

    def action_add_to_later_app(self, open=False) -> None:
        """Add article to Readwise."""
        if not self.configuration.readwise_token:
            self.notify(
                title="Readwise",
                message="No Readwise token found in configuration.",
                timeout=5,
                severity="warning",
            )
            return

        if not hasattr(self, "current_article_url") or not self.current_article_url:
            self.notify(
                title="Readwise",
                message="No article selected or no URL available.",
                timeout=5,
                severity="warning",
            )
            return

        try:
            os.environ["READWISE_TOKEN"] = self.configuration.readwise_token
            import readwise
            from readwise.model import PostResponse

            # Show a progress indicator during the API call
            self.push_screen(screen="progress")

            # Save to Readwise
            response: tuple[bool, PostResponse] = readwise.save_document(
                url=self.current_article_url
            )

            # Remove progress screen
            self.pop_screen()

            if response[1].url and response[1].id:
                self.notify(
                    title="Readwise",
                    message="Article saved to Readwise.",
                    timeout=5,
                )
                if open:
                    webbrowser.open(url=response[1].url)
            else:
                self.notify(
                    title="Readwise",
                    message="Error saving article to Readwise.",
                    timeout=5,
                    severity="error",
                )
        except Exception as err:
            # Make sure to remove progress screen if there's an error
            if isinstance(self.screen, ProgressScreen):
                self.pop_screen()

            logger.error(msg=f"Error saving to Readwise: {err}")
            self.notify(
                title="Readwise",
                message=f"Error: {err!s}",
                timeout=5,
                severity="error",
            )

    def action_add_to_later_app_and_open(self) -> None:
        """Add article to Readwise and open that Readwise page in browser."""
        self.action_add_to_later_app(open=True)

    async def action_clear(self) -> None:
        """Clear content window."""
        self.content_markdown = self.START_TEXT

        # Reset article variables
        self.current_article_title = ""
        self.current_article_url = ""
        self.current_article_urls = []
        self.current_article = None

        try:
            list_view: ListView = self.query_one(
                selector="#articles", expect_type=ListView
            )
            await list_view.clear()
        except Exception:
            pass

        content_view: LinkableMarkdownViewer = self.query_one(
            selector="#content", expect_type=LinkableMarkdownViewer
        )
        await content_view.document.update(markdown=self.content_markdown)

    def action_export_to_obsidian(self) -> None:  # noqa: PLR0912, PLR0915
        """Send the current content as a new note to Obsidian via URI scheme."""
        if not self.configuration.obsidian_vault:
            self.notify(
                title="Obsidian",
                message="No Obsidian vault configured.",
                timeout=5,
                severity="warning",
            )
            return

        if not self.current_article:
            self.notify(
                title="Obsidian",
                message="No article selected.",
                timeout=5,
                severity="warning",
            )
            return

        # Title for the note
        title: str = (
            datetime.now().strftime(format="%Y%m%d%H%M ") + self.current_article_title
            if self.current_article_title
            else datetime.now().strftime(format="%Y-%m-%d %H:%M:%S")
        )
        title = title.replace(":", "-").replace("/", "-").replace("\\", "-")

        if self.configuration.obsidian_folder:
            title = self.configuration.obsidian_folder + "/" + title

        # Use template to create note content
        content: str = self.configuration.obsidian_template.replace(
            "<URL>", self.current_article_url
        )
        content = content.replace("<ID>", datetime.now().strftime(format="%Y%m%d%H%M"))
        content = content.replace("<CONTENT>", self.content_markdown_original)
        content = content.replace("<TITLE>", self.current_article_title)

        # Build tags
        tags: str = self.configuration.obsidian_default_tag + "  \n"
        article_labels: str = ""
        article_tags: str = ""

        if self.show_header and self.configuration.obsidian_include_labels:
            try:
                article_labels = (
                    f"  - {', '.join(item[1] for item in self.current_article.labels)}"  # type: ignore
                    if getattr(self.current_article, "labels", None)
                    else ""
                )
            except (AttributeError, TypeError):
                article_labels = ""

        if self.show_header and self.configuration.obsidian_include_tags:
            try:
                article_tags = "\n".join(
                    f"  - {item}"
                    for item in self.tags.get(self.current_article.id, [])  # type: ignore
                )
            except (KeyError, TypeError):
                article_tags = ""

        tags += article_labels + article_tags
        content = content.replace("<TAGS>", tags)
        content = content.replace("  - \n", "")
        content = content.replace("\n\n", "\n")

        # Encode title and content for URL format
        encoded_title: str = quote(string=title).replace("/", "%2F")
        encoded_content: str = quote(string=content)

        # Check if content is too long for a URI
        max_url_length: int = 8000  # URI length limit is around 8192
        if len(encoded_content) > max_url_length:
            self.notify(
                title="Obsidian",
                message="Content too large for URI. Creating temporary file...",
                timeout=3,
            )

            # Create a temporary file instead
            try:
                temp_path = Path(tempfile.mktemp(suffix=".md"))
                temp_path.write_text(data=content, encoding="utf-8")

                self.temp_files.append(temp_path)  # Track for cleanup

                # Open Obsidian with the file path
                obsidian_uri = f"obsidian://open?vault={self.configuration.obsidian_vault}&file={encoded_title}"
                webbrowser.open(url=obsidian_uri)

                # Wait a moment for Obsidian to open
                sleep(1)

                # Now tell the user to manually import the file
                self.notify(
                    title="Obsidian",
                    message=f"Please import the file manually: {temp_path}",
                    timeout=10,
                )

                # Try to open the file in the default application
                if sys.platform == "win32":
                    os.startfile(temp_path)
                elif sys.platform == "darwin":
                    subprocess.call(args=["open", str(object=temp_path)])
                else:  # Linux and other Unix-like
                    subprocess.call(["xdg-open", str(temp_path)])

            except Exception as e:
                logger.error(msg=f"Error creating temporary file: {e}")
                self.notify(
                    title="Obsidian",
                    message=f"Error creating temporary file: {e}",
                    timeout=5,
                    severity="error",
                )
                return
        else:
            # Construct the Obsidian URI
            obsidian_uri: str = f"obsidian://new?vault={self.configuration.obsidian_vault}&file={encoded_title}&content={encoded_content}"

            # Open the Obsidian URI
            webbrowser.open(url=obsidian_uri)
            self.notify(message=f"Sent to Obsidian: {title}", title="Export Successful")

    def action_focus_next_pane(self) -> None:
        """Move focus to the next pane."""
        panes: list[str] = ["categories", "articles", "content"]
        current_focus: Widget | None = self.focused
        if current_focus:
            current_id: str | None = current_focus.id
            if current_id in panes:
                next_index: int = (panes.index(current_id) + 1) % len(panes)
                next_pane: Widget = self.query_one(selector=f"#{panes[next_index]}")
                next_pane.focus()

    def action_focus_previous_pane(self) -> None:
        """Move focus to the previous pane."""
        panes: list[str] = ["categories", "articles", "content"]
        current_focus: Widget | None = self.focused
        if current_focus:
            current_id: str | None = current_focus.id
            if current_id in panes:
                previous_index: int = (panes.index(current_id) - 1) % len(panes)
                previous_pane: Widget = self.query_one(
                    selector=f"#{panes[previous_index]}"
                )
                previous_pane.focus()

    def action_maximize_content(self) -> None:
        """Maximize the content pane."""
        self.push_screen(
            screen=FullScreenMarkdown(markdown_content=self.content_markdown)
        )

    def action_next_article(self) -> None:
        """Open next article."""
        self.last_key = "j"
        list_view: ListView = self.query_one(selector="#articles", expect_type=ListView)
        list_view.focus()
        list_view.action_cursor_down()

    def action_next_category(self) -> None:
        """Move to next category."""
        list_view: ListView = self.query_one(
            selector="#categories", expect_type=ListView
        )
        list_view.focus()
        if self.first_view:
            self.first_view = False
            self.category_index = 1
        list_view.action_cursor_down()

    def action_open_original_article(self) -> None:
        """Open the original article in a web browser."""
        if hasattr(self, "current_article_url") and self.current_article_url:
            webbrowser.open(url=self.current_article_url)
            self.notify(
                title="Browser", message="Opening article in browser", timeout=3
            )
        else:
            self.notify(
                message="No article selected or no URL available.", title="Info"
            )

    async def action_open_article_url(self) -> None:
        """Open links from the article in a web browser."""
        if hasattr(self, "current_article_urls") and self.current_article_urls:
            self.push_screen(
                screen=LinkSelectionScreen(
                    configuration=self.configuration, links=self.current_article_urls
                )
            )
        else:
            self.notify(message="No links found in article", title="Info")

    def _extract_article_urls(self, soup) -> list[tuple[str, str]]:
        """Extract URLs from article content.

        Args:
            soup: BeautifulSoup object with article HTML

        Returns:
            List of tuples with link title and URL
        """
        urls: list[tuple[str, str]] = []
        if soup is None:
            return urls

        for a in soup.find_all(name="a"):
            try:
                href: str = a.get("href")
                if href:
                    text: str = a.get_text().strip()
                    if not text:  # If link text is empty
                        text = href  # Use the URL as the text
                    urls.append((text, self.get_clean_url(url=href)))
            except Exception as e:
                logger.debug(msg=f"Error processing link: {e}")

        return urls

    async def display_article_content(self, article_id: int) -> None:
        """Fetch, clean, and display the selected article's content.

        Args:
            article_id: ID of the article to display
        """
        try:
            # Fetch the full article
            articles: list[Article] = self.client.get_articles(article_id=article_id)
        except Exception as err:
            logger.error(msg=f"Error fetching article content: {err}")
            self.notify(
                title="Article",
                message=f"Error fetching article content: {err}",
                timeout=5,
                severity="error",
            )
            return

        if not articles:
            self.notify(
                title="Article",
                message=f"No article found with ID {article_id}.",
                timeout=5,
                severity="error",
            )
            return

        try:
            article: Article = articles[0]
            self.current_article = article

            # Parse and clean the HTML
            soup = BeautifulSoup(markup=article.content, features="html.parser")  # type: ignore
            self.current_article_url: str = self.get_clean_url(url=article.link)  # type: ignore
            self.current_article_title: str = article.title  # type: ignore

            # Extract and process images if any
            for img in soup.find_all(name="img"):
                if img.get("src"): # type: ignore
                    # Replace with a placeholder or a note about the image
                    img_text: str = f"[Image: {img.get('alt', 'No description')}]" # type: ignore
                    img.replace_with(soup.new_string(s=img_text))
            
            # Extract URLs from article content
            self.current_article_urls = self._extract_article_urls(soup=soup)

            # Convert HTML to markdown
            self.content_markdown_original: str = markdownify(
                html=str(object=soup)
            ).replace('xml encoding="UTF-8"', "")

            # Clean up the markdown for better readability
            self.content_markdown_original = self._clean_markdown(
                markdown_text=self.content_markdown_original
            )

            # Add header information if enabled
            header: str = self.get_header(article=article)
            self.content_markdown = header + self.content_markdown_original

            # Display the cleaned content
            content_view: LinkableMarkdownViewer = self.query_one(
                selector="#content", expect_type=LinkableMarkdownViewer
            )
            await content_view.document.update(markdown=self.content_markdown)

            # Mark as read if auto-mark-read is enabled
            if self.configuration.auto_mark_read:
                self.client.mark_read(article_id=article_id)
                await self.refresh_categories()
        except Exception as e:
            logger.error(msg=f"Error processing article content: {e}")
            self.notify(
                title="Error",
                message=f"Error processing article: {e!s}",
                timeout=5,
                severity="error",
            )

    def action_previous_article(self) -> None:
        """Open previous article."""
        self.last_key = "k"
        list_view: ListView = self.query_one(selector="#articles", expect_type=ListView)
        list_view.focus()
        if not list_view.index == 0 or (self.group_feeds and list_view.index == 1):
            list_view.action_cursor_up()

    def action_previous_category(self) -> None:
        """Move to previous category."""
        list_view: ListView = self.query_one(
            selector="#categories", expect_type=ListView
        )
        list_view.focus()
        if self.first_view:
            self.first_view = False
            self.category_index = 0
        list_view.action_cursor_up()

    async def action_recently_read(self) -> None:
        """Open recently read articles."""
        self.show_special_categories = True
        self.last_key = "R"
        await self.refresh_categories()

    def action_readwise_article_url(self) -> None:
        """Add one article link to Readwise."""
        if not self.configuration.readwise_token:
            self.notify(
                title="Readwise",
                message="No Readwise token found in configuration.",
                timeout=5,
                severity="warning",
            )
            return

        if not hasattr(self, "current_article_urls") or not self.current_article_urls:
            self.notify(
                title="Readwise",
                message="No links found in article.",
                timeout=5,
                severity="warning",
            )
            return

        self.push_screen(
            screen=LinkSelectionScreen(
                configuration=self.configuration,
                links=self.current_article_urls,
                open_links="readwise",
            )
        )

    def action_readwise_article_url_and_open(self) -> None:
        """Add one article link to Readwise and open in browser."""
        if not self.configuration.readwise_token:
            self.notify(
                title="Readwise",
                message="No Readwise token found in configuration.",
                timeout=5,
                severity="warning",
            )
            return

        if not hasattr(self, "current_article_urls") or not self.current_article_urls:
            self.notify(
                title="Readwise",
                message="No links found in article.",
                timeout=5,
                severity="warning",
            )
            return

        self.push_screen(
            screen=LinkSelectionScreen(
                configuration=self.configuration,
                links=self.current_article_urls,
                open_links="readwise",
                open=True,
            )
        )

    @work
    async def action_refresh(self) -> None:
        """Refresh categories and articles from the server."""
        self.client.clear_cache()  # Clear cache to force fresh data
        self.notify(message="Refreshing data from server...", title="Refresh")
        await self.refresh_categories()
        await self.refresh_articles()
        self.notify(message="Refresh complete", title="Refresh")

    async def action_search(self) -> None:
        """Search for articles."""
        search_term = await self.push_screen_wait(screen="search")
        if search_term:
            self.notify(message=f"Searching for: {search_term}", title="Search")
            # Implement search functionality here
            # This would require extending the Tiny Tiny RSS client
            # For now, just show a notification
            self.notify(
                message=f"Search functionality is not fully implemented yet. Would search for: {search_term}",
                title="Search",
            )

    def action_save_article_url(self) -> None:
        """Save selected link from article to download folder."""
        if hasattr(self, "current_article_urls") and self.current_article_urls:
            self.push_screen(
                screen=LinkSelectionScreen(
                    configuration=self.configuration,
                    links=self.current_article_urls,
                    open_links="download",
                )
            )
        else:
            self.notify(
                title="Save link",
                message="No links found in article.",
                timeout=5,
                severity="warning",
            )

    def action_show_version(self) -> None:
        """Show version information."""
        version_info: str = (
            f"ttrsscli version: {self.configuration.version}\n"
            f"Python: {sys.version.split()[0]}\n"
            f"Textual: {metadata.version(distribution_name='textual')}"
        )
        self.notify(
            title="Version Info",
            message=version_info,
            timeout=5,
            severity="information",
        )

    async def action_toggle_category(self) -> None:
        """Toggle category expansion."""
        self.expand_category = not self.expand_category
        await self.refresh_categories()

    def action_toggle_clean_url(self) -> None:
        """Toggle URL cleaning."""
        self.clean_url = not self.clean_url
        if self.clean_url:
            self.notify(message="Clean URLs enabled", title="Info")
        else:
            self.notify(message="Clean URLs disabled", title="Info")

    def action_toggle_dark(self) -> None:
        """Toggle dark mode."""
        self.theme = (
            "textual-dark" if self.theme == "textual-light" else "textual-light"
        )

    async def action_toggle_header(self) -> None:
        """Toggle header info for article."""
        self.show_header = not self.show_header
        if self.current_article and self.current_article.id:  # type: ignore
            await self.display_article_content(article_id=self.current_article.id)  # type: ignore

    async def action_toggle_feeds(self) -> None:
        """Toggle feed grouping."""
        self.group_feeds = not self.group_feeds
        await self.refresh_articles()

    def action_toggle_help(self) -> None:
        """Toggle the help screen."""
        if isinstance(self.screen, HelpScreen):
            self.pop_screen()
        else:
            self.push_screen(screen=HelpScreen())

    def action_toggle_read(self) -> None:
        """Toggle article read/unread status."""
        if hasattr(self, "article_id") and self.article_id:
            try:
                self.client.toggle_unread(article_id=self.article_id)
                self.notify(message="Article status toggled", title="Info")
            except Exception as e:
                logger.error(msg=f"Error toggling article status: {e}")
                self.notify(
                    title="Error",
                    message=f"Failed to toggle article status: {e!s}",
                    timeout=5,
                    severity="error",
                )
        else:
            self.notify(
                title="Article",
                message="No article selected.",
                timeout=5,
                severity="warning",
            )

    async def action_toggle_special_categories(self) -> None:
        """Toggle special categories."""
        self.show_special_categories = not self.show_special_categories
        self.last_key = "S"
        article_list: ListView = self.query_one(
            selector="#articles", expect_type=ListView
        )
        await article_list.clear()
        await self.refresh_categories()

    def action_toggle_star(self) -> None:
        """Toggle article star status."""
        if hasattr(self, "article_id") and self.article_id:
            try:
                self.client.toggle_starred(article_id=self.article_id)
                self.notify(message="Article star status toggled", title="Info")
            except Exception as e:
                logger.error(msg=f"Error toggling star status: {e}")
                self.notify(
                    title="Error",
                    message=f"Failed to toggle star status: {e!s}",
                    timeout=5,
                    severity="error",
                )
        else:
            self.notify(
                title="Article",
                message="No article selected.",
                timeout=5,
                severity="warning",
            )

    async def action_toggle_unread(self) -> None:
        """Toggle unread-only mode."""
        self.show_unread_only = not self.show_unread_only
        await self.refresh_categories()
        await self.refresh_articles()

    def action_view_markdown_source(self) -> None:
        """View markdown source."""
        if isinstance(self.screen, FullScreenTextArea):
            self.pop_screen()
        else:
            self.push_screen(screen=FullScreenTextArea(text=str(object=self.content_markdown)))

    def _clean_markdown(self, markdown_text: str) -> str:
        """Clean up markdown text for better readability.

        Args:
            markdown_text: Raw markdown text

        Returns:
            Cleaned markdown text
        """
        # Replace multiple consecutive blank lines with a single one
        import re

        markdown_text = re.sub(pattern=r"\n{3,}", repl="\n\n", string=markdown_text)

        # Wrap very long lines for better readability
        lines: list[str] = markdown_text.split(sep="\n")
        wrapped_lines = []

        for line in lines:
            # Don't wrap lines that look like Markdown formatting (headers, lists, code blocks)
            if (
                line.startswith("#")
                or line.startswith("```")
                or line.startswith("- ")
                or line.startswith("* ")
                or line.startswith("> ")
                or line.startswith("|")
                or line.strip() == ""
            ):
                wrapped_lines.append(line)
            else:
                # Wrap long text lines
                wrapped: str = textwrap.fill(text=line, width=10000)
                wrapped_lines.append(wrapped)

        return "\n  ".join(wrapped_lines)

    def get_clean_url(self, url: str) -> str:
        """Clean URL using cleanurl if enabled.

        Args:
            url: URL to clean

        Returns:
            Cleaned URL or original URL
        """
        if not url:
            return ""

        if self.clean_url:
            try:
                cleaned_url: Result | None = cleanurl(url=url)
                if cleaned_url:
                    return cleaned_url.url
            except Exception as e:
                logger.debug(msg=f"Error cleaning URL {url}: {e}")

        return url

    def get_header(self, article: Article) -> str:
        """Get header info for article.

        Args:
            article: Article object

        Returns:
            Formatted header string
        """
        if not self.show_header:
            return ""

        header_items = []

        # Add basic article info
        header_items.append(f"> **Title:** {self.current_article_title}  ")
        header_items.append(f"> **URL:** {self.current_article_url}  ")

        # Add article metadata if available
        for field, label in [
            ("author", "Author"),
            ("published", "Published"),
            ("updated", "Updated"),
            ("note", "Note"),
            ("feed_title", "Feed"),
            ("lang", "Language"),
        ]:
            value = getattr(article, field, None)
            if value:
                header_items.append(f"> **{label}:** {value}  ")

        # Add labels if available
        try:
            if hasattr(article, "labels") and article.labels:  # type: ignore
                labels: str = ", ".join(item[1] for item in article.labels)  # type: ignore
                if labels:
                    header_items.append(f"> **Labels:** {labels}  ")
        except (AttributeError, TypeError):
            pass

        # Add tags if available
        try:
            article_tags = self.tags.get(article.id, [])  # type: ignore
            if article_tags and len(article_tags[0]) > 0:
                tags: str = ", ".join(article_tags)
                header_items.append(f"> **Tags:** {tags}  ")
        except (KeyError, IndexError, TypeError):
            pass

        # Add starred status
        if hasattr(article, "marked") and article.marked:  # type: ignore
            header_items.append(f"> **Starred:** {article.marked}  ")  # type: ignore

        # Combine all header items and add a separator
        header: str = "\n".join(header_items)
        if header:
            header += "\n\n"

        return header

    async def refresh_articles(self, show_id=None) -> None:  # noqa: PLR0912, PLR0915
        """Load articles from selected category or feed.

        Args:
            show_id: ID of category or feed to show articles for
        """
        article_ids: list[str] = []

        view_mode: Literal["all_articles"] | Literal["unread"] = (
            "all_articles" if self.show_special_categories else "unread"
        )

        # Determine if the selected item is a category or feed
        # Show all articles by default
        feed_id = -4
        is_cat = False
        if (
            not isinstance(show_id, int)
            and not show_id is None
            and show_id.startswith("feed_")
        ):
            # We have a feed ID
            feed_id: int = int(show_id.replace("feed_", ""))
            is_cat = False
        elif show_id is not None:
            # We have a category ID
            feed_id = show_id
            is_cat = True

        # Clear the article list view
        list_view: ListView = self.query_one(selector="#articles", expect_type=ListView)
        await list_view.clear()

        try:
            articles: list[Headline] = self.client.get_headlines(
                feed_id=feed_id, is_cat=is_cat, view_mode=view_mode
            )

            # Sort articles, first by feed title, then by published date (newest first)
            articles.sort(key=lambda a: a.feed_title or "")  # type: ignore

            feed_title: str = ""
            for article in articles:
                self.tags[article.id] = article.tags  # type: ignore
                prepend: str = ""

                # Add feed title header if grouping by feeds is enabled and this is a new feed
                if self.group_feeds and article.feed_title not in [feed_title, ""]:  # type: ignore
                    article_id: str = f"ft_{article.feed_id}"  # type: ignore
                    feed_title = html.unescape(article.feed_title.strip())  # type: ignore
                    if article_id not in article_ids:
                        feed_title_item = ListItem(
                            Static(content=feed_title), id=article_id
                        )
                        feed_title_item.styles.color = "white"
                        feed_title_item.styles.background = "blue"
                        list_view.append(item=feed_title_item)
                        article_ids.append(article_id)

                # Add article to list
                if article.title != "":  # type: ignore
                    article_id = f"art_{article.id}"  # type: ignore
                    if article_id not in article_ids:
                        # Style based on read status
                        style: str = "bold" if article.unread else "none"  # type: ignore

                        # Add indicators for special properties
                        if article.note or article.published or article.marked:  # type: ignore
                            prepend = "("
                            prepend += "N" if article.note else ""  # type: ignore
                            if article.published:  # type: ignore
                                prepend += "P" if prepend == "(" else ", P"
                            if article.marked:  # type: ignore
                                prepend += "S" if prepend == "(" else ", S"
                            prepend += ") "

                        # Format article title
                        article_title: str = html.unescape(
                            prepend + article.title.strip()  # type: ignore
                        )

                        # Create list item
                        article_title_item = ListItem(
                            Static(content=article_title), id=article_id
                        )
                        article_title_item.styles.text_style = style

                        # Mark item as highlighted if it's been selected before
                        if int(article.id) in self.selected_article_ids:  # type: ignore
                            article_title_item.styles.text_style = "none"

                        list_view.append(item=article_title_item)
                        article_ids.append(article_id)

            if not articles:
                await self.action_clear()

        except Exception as err:
            logger.error(msg=f"Error fetching articles: {err}")
            self.notify(
                title="Articles",
                message=f"Error fetching articles: {err}",
                timeout=5,
                severity="error",
            )

    async def refresh_categories(self) -> None:
        """Load categories from TTRSS and filter based on unread-only mode."""
        try:
            existing_ids: list[str] = []

            # Get all categories
            categories: list[Category] = self.client.get_categories()

            # Get ListView for categories and clear it
            list_view: ListView = self.query_one(
                selector="#categories", expect_type=ListView
            )
            await list_view.clear()

            unread_only: bool = False if self.show_special_categories else True
            max_length: int = 0

            if categories:
                # Sort categories by title
                sorted_categories: list[Category] = sorted(
                    categories, key=lambda x: x.title  # type: ignore
                )  # type: ignore

                for category in sorted_categories:
                    # Skip categories with no unread articles if unread-only mode is enabled and special categories are hidden
                    if (
                        not self.show_special_categories
                        and self.show_unread_only
                        and category.unread == 0  # type: ignore
                    ):
                        continue

                    # category_id is used if expand_category is enabled
                    category_id: str = f"cat_{category.id}"  # type: ignore

                    # Handle top-level categories
                    if category_id not in existing_ids:
                        # Handle special categories view
                        if self.show_special_categories and category.title == "Special":  # type: ignore
                            article_count: str = (
                                f" ({category.unread})" if category.unread else ""  # type: ignore
                            )
                            max_length = max(max_length, len(category.title))  # type: ignore
                            list_view.append(
                                item=ListItem(
                                    Static(content=category.title + article_count),  # type: ignore
                                    id=category_id,
                                )
                            )
                        # Handle normal categories
                        elif (
                            not self.show_special_categories
                            and category.title != "Special"  # type: ignore
                        ):
                            article_count: str = (
                                f" ({category.unread})" if category.unread else ""  # type: ignore
                            )
                            max_length = max(max_length, len(category.title))  # type: ignore
                            list_view.append(
                                item=ListItem(
                                    Static(content=category.title + article_count),  # type: ignore
                                    id=category_id,
                                )
                            )
                        existing_ids.append(category_id)

                    # Expand category view to show feeds or show special categories (always expanded)
                    if (
                        self.expand_category
                        and self.category_id == category_id
                        and not self.show_special_categories
                    ) or (self.show_special_categories and category.title == "Special"):  # type: ignore
                        feeds: list[Feed] = self.client.get_feeds(
                            cat_id=category.id,  # type: ignore
                            unread_only=unread_only,
                        )
                        for feed in feeds:
                            feed_id: str = f"feed_{feed.id}"  # type: ignore
                            if feed_id not in existing_ids:
                                feed_unread_count: str = (
                                    f" ({feed.unread})" if feed.unread else ""  # type: ignore
                                )
                                max_length = max(max_length, len(feed.title) + 3)  # type: ignore
                                list_view.append(
                                    item=ListItem(
                                        Static(
                                            content="  "
                                            + feed.title  # type: ignore
                                            + feed_unread_count
                                        ),
                                        id=feed_id,
                                    )
                                )
                                existing_ids.append(feed_id)

                        # Set cursor position based on last key press
                        if self.show_special_categories and self.last_key == "S":
                            list_view.index = 1
                            self.last_key = ""
                        elif self.last_key == "R":
                            list_view.index = 5
                            self.last_key = ""

            # Set category listview width based on longest category name
            estimated_width: int = max(max_length + 5, 15)
            estimated_width = min(estimated_width, 80)
            list_view.styles.width = estimated_width

        except Exception as err:
            logger.error(msg=f"Error refreshing categories: {err}")
            self.notify(
                title="Categories",
                message=f"Error refreshing categories: {err}",
                timeout=5,
                severity="error",
            )

    def on_unmount(self) -> None:
        """Clean up resources when app is closed."""
        # Clean up any temporary files
        for temp_file in self.temp_files:
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except Exception as e:
                logger.error(msg=f"Error removing temporary file {temp_file}: {e}")

        # Close the HTTP client
        if hasattr(self, "http_client"):
            self.http_client.close()


def main() -> None:
    """Run the ttcli app."""
    try:
        app.run()
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        print("\nExiting ttrsscli...")
    except Exception as e:
        logger.error(msg=f"Unhandled exception: {e}")
        print(f"Error: {e}")
        print("See ttrsscli.log for details")
        sys.exit(1)


def main_web() -> None:
    """Run the ttcli app in web mode."""
    from textual_serve.server import Server

    app = Server(command="ttrsscli")
    app.serve()

app = ttrsscli()

if __name__ == "__main__":
    app.run()
