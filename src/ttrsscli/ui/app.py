"""Main application class for ttrsscli."""

import html
import logging
import os
import sys
import tempfile
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Literal

import httpx
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Footer, Header, ListItem, ListView, Static
from ttrss.client import Article
from ttrss.exceptions import TTRNotLoggedIn
from urllib3.exceptions import NameResolutionError

from ..cache import LimitedSizeDict
from ..client import TTRSSClient
from ..config import Configuration
from ..utils.markdown_converter import (
    escape_markdown_formatting,
    extract_links,
    render_html_to_markdown,
)
from ..utils.url import get_clean_url
from .screens import (
    AddFeedScreen,
    ConfirmMarkAllReadScreen,
    ConfirmScreen,
    EditFeedScreen,
    FullScreenMarkdown,
    FullScreenTextArea,
    HelpScreen,
    LinkSelectionScreen,
    ProgressScreen,
    SearchScreen,
)
from .widgets import LinkableMarkdownViewer

logger: logging.Logger = logging.getLogger(name=__name__)


class ttrsscli(App[None]):
    """A Textual app to access and read articles from Tiny Tiny RSS."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("?", "toggle_help", "Help"),
        ("a", "add_feed", "Add Feed"),
        ("A", "mark_all_read", "Mark all read"),
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
        "add_feed": AddFeedScreen,
        "confirm": ConfirmScreen,
        "confirm_mark_all_read": ConfirmMarkAllReadScreen,
        "edit_feed": EditFeedScreen,
        "help": HelpScreen,
        "search": SearchScreen,
        "progress": ProgressScreen,
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
                yield LinkableMarkdownViewer(markdown=self.START_TEXT, id="content", show_table_of_contents=False, open_links=False)
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
                    self.category_id = highlighted_item.id
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

        # Update the content using LinkableMarkdownViewer
        content_view: Widget = self.query_one(selector="#content")
        await content_view.remove()

        logger.debug(msg=f"Content markdown length: {len(self.content_markdown)}")
        logger.debug(msg=f"Content sample: {self.content_markdown[:100]}")

        # Then create and mount a new one
        new_viewer = LinkableMarkdownViewer(
            markdown=self.content_markdown,
            id="content",
            show_table_of_contents=False,
            open_links=False
        )
        content_container: Widget = self.query_one(selector="Vertical")
        await content_container.mount(new_viewer)

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
        from urllib.parse import quote
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
                from time import sleep
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
                    import subprocess
                    subprocess.call(args=["open", str(object=temp_path)])
                else:  # Linux and other Unix-like
                    import subprocess
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
        except IndexError:
            self.notify(
                title="Article",
                message=f"No article found with ID {article_id}.",
                timeout=5,
                severity="error",
            )
            return

        self.current_article = article

        # Get clean URL and title
        self.current_article_url: str = get_clean_url(
            url=article.link,  # type: ignore
            clean_url_enabled=self.clean_url
        )

        # Safely handle the article title - this is where the problem occurs
        if hasattr(article, 'title') and article.title: # type: ignore
            raw_title = str(article.title) # type: ignore
            # Special handling for problematic titles with Textual markup characters
            if raw_title.startswith("[$]"):
                # Prefix with escape character to prevent Textual from interpreting as markup
                self.current_article_title = "\\[$]" + raw_title[3:]
            else:
                self.current_article_title = raw_title
        else:
            self.current_article_title = "Untitled"

        # Escape special markdown formatting in the title
        self.current_article_title = escape_markdown_formatting(text=self.current_article_title)

        # Get article content
        self.content_markdown_original: str = render_html_to_markdown(
            html_content=article.content,  # type: ignore
            clean_urls=self.clean_url
        )

        # Extract links
        self.current_article_urls = extract_links(
            markdown_text=article.content  # type: ignore
        )

        # Add header information if enabled
        header: str = self.get_header(article=article)
        self.content_markdown = header + self.content_markdown_original

        # Display the content using our markdown view
        try:
            content_view: Widget = self.query_one(selector="#content")
            await content_view.remove()
            logger.debug(msg="Removed old content view")

            # Then create and mount a new one
            new_viewer = LinkableMarkdownViewer(
                markdown=self.content_markdown,
                id="content",
                show_table_of_contents=False,
                open_links=False
            )
            logger.debug(msg="Created new viewer")

            content_container: Widget = self.query_one(selector="Vertical")
            await content_container.mount(new_viewer)
            logger.debug("Mounted new viewer")
        except Exception as e:
            logger.error(f"Error during viewer replacement: {e}")
            self.notify(
                title="Viewer Error",
                message=f"Error displaying content: {e}",
                timeout=5,
                severity="error",
            )

        # Mark as read if auto-mark-read is enabled
        if self.configuration.auto_mark_read:
            self.client.mark_read(article_id=article_id)
            await self.refresh_categories()

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
        from importlib import metadata

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
                self.notify(message="Article read status toggled", title="Info")
            except Exception as e:
                logger.error(msg=f"Error toggling article read status: {e}")
                self.notify(
                    title="Error",
                    message=f"Failed to toggle article read status: {e!s}",
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

    def get_header(self, article: Article) -> str:  # noqa: PLR0912
        """Get header info for article.

        Args:
            article: Article object

        Returns:
            Formatted header string
        """
        if not self.show_header:
            return ""

        header_items = []

        header_items.append(f"> **Title:** {self.current_article_title.replace('\\[', '[')}  ")
        header_items.append(f"> **URL:** {self.current_article_url}  ")

        # Add article metadata if available
        for field, label in [
            ("author", "Author"),
            ("published", "Published"),
            ("updated", "Updated"),
            ("note", "Note"),
            ("feed_title", "Feed"),
            ("lang", "Language"),
            ("feed_id", "Feed ID"),
        ]:
            value = getattr(article, field, None)
            if value:
                # Escape special markdown characters in values if they're strings
                if isinstance(value, str):
                    safe_value = escape_markdown_formatting(value)
                    header_items.append(f"> **{label}:** {safe_value}  ")
                else:
                    header_items.append(f"> **{label}:** {value}  ")

        # Add labels if available
        try:
            if hasattr(article, "labels") and article.labels:  # type: ignore
                # Process each label to escape special characters
                safe_labels = []
                for label_tuple in article.labels:  # type: ignore
                    if len(label_tuple) > 1:
                        label_text = escape_markdown_formatting(label_tuple[1])
                        safe_labels.append(label_text)

                if safe_labels:
                    labels: str = ", ".join(safe_labels)
                    header_items.append(f"> **Labels:** {labels}  ")
        except (AttributeError, TypeError):
            pass

        # Add tags if available
        try:
            article_tags = self.tags.get(article.id, [])  # type: ignore
            if article_tags and len(article_tags[0]) > 0:
                # Process each tag to escape special characters
                safe_tags = []
                for tag in article_tags:
                    safe_tag = escape_markdown_formatting(tag)
                    # Additional protection for Textual markup
                    safe_tag = safe_tag.replace("[", "\\[")
                    safe_tags.append(safe_tag)

                tags: str = ", ".join(safe_tags)
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
            articles: list[Article] = self.client.get_headlines(
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

                # Add the article to list
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

                        # Format article title - we don't need to escape here since Static widget
                        # displays plain text, not markdown
                        article_title: str = html.unescape(
                            prepend + escape_markdown_formatting(text=article.title.strip())  # type: ignore
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
            categories = self.client.get_categories()

            # Get ListView for categories and clear it
            list_view: ListView = self.query_one(
                selector="#categories", expect_type=ListView
            )
            await list_view.clear()

            unread_only: bool = False if self.show_special_categories else True
            max_length: int = 0

            if categories:
                # Sort categories by title
                sorted_categories = sorted(
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
                        feeds = self.client.get_feeds(
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

    @work
    async def action_mark_all_read(self) -> None:  # noqa: PLR0912
        """Mark all articles in the selected feed or category as read."""
        feed_id = None
        feed_title: str = ""
        is_cat = False

        # Determine if a feed or category is selected
        if hasattr(self, "category_id") and self.category_id:
            if self.category_id.startswith("feed_"):
                # We have a feed ID
                feed_id = int(self.category_id.replace("feed_", ""))
                is_cat = False

                # Try to get feed title
                try:
                    feed_props = self.client.get_feed_properties(feed_id=feed_id)
                    if feed_props and hasattr(feed_props, "title"):
                        feed_title = feed_props.title
                    else:
                        feed_title = "this feed"
                except Exception as e:
                    logger.debug(msg=f"Error getting feed title: {e}")
                    feed_title = "this feed"

            elif self.category_id.startswith("cat_"):
                # We have a category ID
                feed_id = int(self.category_id.replace("cat_", ""))
                is_cat = True

                # Try to get category title
                try:
                    categories = self.client.get_categories()
                    for category in categories:
                        if int(category.id) == feed_id: # type: ignore
                            feed_title = category.title # type: ignore
                            break
                    if not feed_title:
                        feed_title = "this category"
                except Exception as e:
                    logger.debug(msg=f"Error getting category title: {e}")
                    feed_title = "this category"

        if not feed_id:
            self.notify(
                message="Please select a feed or category first",
                title="Mark All as Read",
                severity="warning",
            )
            return

        # Show confirmation dialog
        confirm_screen = ConfirmMarkAllReadScreen(
            feed_id=feed_id,
            is_cat=is_cat,
            feed_title=feed_title
        )
        result = await self.push_screen_wait(screen=confirm_screen)

        if result and result.get("confirm"):
            try:
                # Mark all as read for the specific feed only
                success = self.client.mark_all_read(feed_id=feed_id, is_cat=is_cat)

                if success:
                    # Refresh the UI
                    self.notify(
                        message=f"Marked all articles in '{feed_title}' as read",
                        title="Success"
                    )
                    await self.refresh_categories()
                    await self.refresh_articles(show_id=self.category_id)
                else:
                    raise Exception("Failed to mark all as read")
            except Exception as e:
                logger.error(msg=f"Error marking all as read: {e}")
                self.notify(
                    message=f"Error marking all as read: {e}",
                    title="Error",
                    severity="error"
                )
