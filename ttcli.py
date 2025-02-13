"""Command line tool to access Tiny Tiny RSS."""
import html
import subprocess
import sys
import webbrowser
from collections.abc import Generator
from typing import Any, ClassVar

import toml
from bs4 import BeautifulSoup
from markdownify import markdownify
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import (
    Footer,
    Header,
    ListItem,
    ListView,
    Markdown,
    MarkdownViewer,
    Static,
    TextArea,
)
from ttrss.client import Article, Category, Feed, Headline, TTRClient
from ttrss.exceptions import TTRNotLoggedIn
from urllib3.exceptions import NameResolutionError


# Helper function to retrieve credentials from 1Password CLI
def get_conf_value(op_command) -> str:
    """Get the configuration value."""
    if op_command.startswith("op "):
        try:
            result: subprocess.CompletedProcess[str] = subprocess.run(op_command.split(), capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as err:
            print(f"Error executing command '{op_command}': {err}")
            sys.exit(1)
        except FileNotFoundError:
            print("Error: 'op' command not found. Ensure 1Password CLI is installed and accessible.")
            sys.exit(1)
        except NameResolutionError:
            print("Error: Couldn't look up server for url.")
            sys.exit(1)
    else:
        return op_command

# Load configuration
try:
    config: dict[str, Any] = toml.load("config.toml")
    api_url: str = get_conf_value(op_command=config["ttrss"].get("api_url", ""))
    username: str = get_conf_value(op_command=config["ttrss"].get("username", ""))
    password: str = get_conf_value(op_command=config["ttrss"].get("password", ""))
except (FileNotFoundError, toml.TomlDecodeError) as err:
    print(f"Error reading configuration file: {err}")
    sys.exit(1)

# Shared constants
ALLOW_IN_FULL_SCREEN: list[str] = ["arrow_up", "arrow_down", "page_up", "page_down", "down", "up", "right", "left"]

# Connect to TTRSS
try:
    client = TTRClient(url=api_url, user=username, password=password, auto_login=True)
    client.login()
except TTRNotLoggedIn:
    print("Error: Could not log in to Tiny Tiny RSS. Check your credentials.")
    sys.exit(1)
except NameResolutionError:
    print("Error: Couldn't look up server for url.")
    sys.exit(1)


class LinkableMarkdownViewer(MarkdownViewer):
    """An extended MarkdownViewer that allows web links to be clicked."""

    @on(message_type=Markdown.LinkClicked)
    def handle_link(self, event: Markdown.LinkClicked) -> None:
        """Open links in the default web browser."""
        if event.href:
            event.prevent_default()
            webbrowser.open(url=event.href)


class FullScreenMarkdown(Screen):
    """A full-screen Markdown viewer."""
    def __init__(self, markdown_content: str) -> None:
        """Initialize the full-screen Markdown viewer."""
        super().__init__()
        self.markdown_content: str = markdown_content

    def compose(self) -> Generator[LinkableMarkdownViewer, Any, None]:
        """Define the content layout of the full-screen Markdown viewer."""
        yield LinkableMarkdownViewer(markdown=self.markdown_content, show_table_of_contents=True)
    
    def on_key(self, event) -> None:
        """Close the full-screen Markdown viewer on any key press."""
        if event.key in ALLOW_IN_FULL_SCREEN:
            pass
        else:
            self.app.pop_screen()


class FullScreenTextArea(Screen):
    """A full-screen TextArea."""
    def __init__(self, text: str) -> None:
        """Initialize the full-screen TextArea."""
        super().__init__()
        self.text: str = text

    def compose(self) -> Generator[TextArea, Any, None]:
        """Define the content layout of the full-screen TextArea."""
        yield TextArea.code_editor(text=self.text, language="markdown", read_only=True)
    
    def on_key(self, event) -> None:
        """Close the full-screen TextArea on any key press."""
        print(event.key)
        if event.key in ALLOW_IN_FULL_SCREEN:
            pass
        else:
            self.app.pop_screen()


class HelpScreen(Screen):
    """A modal help screen."""

    def compose(self) -> ComposeResult:
        """Define the content layout of the help screen."""
        yield LinkableMarkdownViewer(
            markdown="""# Help for ttcli

Key bindings:
- **h / H / ?**: Show this help
- **c**: Clear content in article pane
- **ctrl+s**: View markdown source
- **d**: Toggle dark mode
- **e**: Toggle expand category
- **g**: Toggle group feeds
- **G / ,**: Refresh
- **j / k / n**: Navigate articles
- **J / K**: Navigate categories
- **m**: Maximize content pane (ESC to minimize)
- **o**: Open article in browser
- **q**: Quit
- **R**: Open recently read articles
- **r**: Toggle read/unread
- **S**: Show special categories
- **s**: Star article
- **u**: Toggle unread only
- **r**: Mark read/unread
- **s**: Star article
- **u**: Show unread categories
- **tab / shift+tab**: Navigate panes

For more information, see the [GitHub repository](https://github.com/reuteras/ttcli) for ttcli. For more about Tiny Tiny RSS, see the [Tiny Tiny RSS website](https://tt-rss.org/).
""",
            id="fullscreen-content",
            show_table_of_contents=False,
            open_links=False
        )


class ttcli(App):
    """A Textual app to access and read articles from Tiny Tiny RSS."""
    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("?", "toggle_help", "Help"),
        ("c", "clear", "Clear"),
        ("comma", "refresh", "Refresh"),
        ("ctrl+s", "view_source", "View md source"),
        ("d", "toggle_dark", "Toggle dark mode"),
        ("e", "toggle_category", "Toggle category selection"),
        ("G", "refresh", "Refresh"),
        ("g", "toggle_feeds", "Group feeds"),
        ("h", "toggle_help", "Help"),
        ("H", "toggle_help", "Help"),
        ("J", "next_category", "Next category"),
        ("j", "next_article", "Next article"),
        ("K", "previous_category", "Previous category"),
        ("k", "previous_article", "Previous article"),
        ("l", "add_to_later_app", "Add to later app (NOT implemented)"),
        ("m", "maximize_content", "Maximize content pane"),
        ("n", "next_article", "Next article"),
        ("o", "open_original_article", "Open article in browser"),
        ("q", "quit", "Quit"),
        ("R", "recently_read", "Open recently read articles"),
        ("r", "toggle_read", "Mark Read/Unread"),
        ("S", "toggle_special_categories", "Show special categories"),
        ("s", "toggle_star", "Star article"),
        ("shift+tab", "focus_previous_pane", "Previous pane"),
        ("tab", "focus_next_pane", "Next pane"),
        ("u", "toggle_unread", "Show categories with unread articles"),
    ]
    SCREENS: ClassVar[dict[str, type[Screen]]] = {
        "help": HelpScreen,
    }
    CSS_PATH: str = "styles.tcss"
    START_TEXT: str = "Welcome to ttcli TUI! A text-based interface to Tiny Tiny RSS."

    # State variables

    # Current article ID
    article_id: int = 0
    # Current category ID
    category_id = None
    # Current category index position
    category_index: int = 0
    # Content pane markdown content
    content_markdown: str = START_TEXT
    # Current article URL (for opening in browser with 'o')
    current_article_url = None
    # Expand category view to show feeds for selected category
    expand_category: bool = False
    # First view flag used when first started
    first_view: bool = True
    # Group articles by feed
    group_feeds: bool = True
    # Last key pressed (for j/k navigation)
    last_key: str = ""
    # Show unread categories only
    show_unread_only = reactive(default=True)
    # Show special categories
    show_special_categories: bool = False

    def compose(self) -> ComposeResult:
        """Compose the layout."""
        yield Header(show_clock=True, name="ttcli")
        with Horizontal():
            yield ListView(id="categories")
            with Vertical():
                yield ListView(id="articles")
                yield LinkableMarkdownViewer(id="content", show_table_of_contents=False, markdown=self.START_TEXT)
        yield Footer()

    async def on_list_view_highlighted(self, message: Message) -> None:
        """Called when an item is highlighted in the ListView."""
        highlighted_item = message.item

        if highlighted_item:
            # Update category index position for navigation
            if hasattr(highlighted_item, "parent") and hasattr(highlighted_item.parent, "index"):
                self.category_index = highlighted_item.parent.index

            # Handle category selection -> refresh articles
            if highlighted_item.id.startswith("cat_"):
                category_id = int(highlighted_item.id.replace("cat_", ""))
                self.category_id = highlighted_item.id
                await self.refresh_articles(show_id=category_id)

            # Handle feed selection in expanded category view -> refresh articles
            elif highlighted_item.id.startswith("feed_"):
                await self.refresh_articles(show_id=highlighted_item.id)

            # Handle feed title selection in article list -> navigate articles
            elif highlighted_item.id.startswith("ft_"):
                if self.last_key == "j":
                    self.action_next_article()
                elif self.last_key == "k":
                    if highlighted_item.parent.index == 0:
                        self.action_next_article()
                    else:
                        self.action_previous_article()

            # Handle article selection -> display selected article content
            elif highlighted_item.id.startswith("art_"):
                article_id = int(highlighted_item.id.replace("art_", ""))
                self.article_id: int = article_id
                highlighted_item.styles.text_style = "none"
                await self.display_article_content(article_id=article_id)

    async def on_list_view_selected(self, message: Message) -> None:
        """Called when an item is selected in the ListView."""
        selected_item = message.item

        if selected_item:
            # Handle category selection
            if selected_item.id.startswith("cat_"):
                category_id = int(selected_item.id.replace("cat_", ""))
                await self.refresh_articles(show_id=category_id)
                self.action_focus_next_pane()

            # Handle article selection
            elif selected_item.id.startswith("art_"):
                article_id = int(selected_item.id.replace("art_", ""))
                self.article_id = article_id
                selected_item.styles.text_style = "none"
                await self.display_article_content(article_id=article_id)

    async def on_mount(self) -> None:
        """Fetch and display categories on startup."""
        await self.refresh_categories()
        await self.refresh_articles()

    async def action_clear(self) -> None:
        """Clear content window."""
        self.content_markdown = self.START_TEXT
        content_view: LinkableMarkdownViewer = self.query_one(selector="#content", expect_type=LinkableMarkdownViewer)
        await content_view.document.update(markdown=self.content_markdown)

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
                previous_pane: Widget = self.query_one(selector=f"#{panes[previous_index]}")
                previous_pane.focus()

    def action_maximize_content(self) -> None:
        """Maximize the content pane."""
        if isinstance(self.screen, FullScreenMarkdown):
            self.pop_screen()
        else:
            self.push_screen(screen=FullScreenMarkdown(markdown_content=self.content_markdown))

    def action_next_article(self) -> None:
        """Open next article."""
        self.last_key = "j"
        list_view: ListView = self.query_one(selector="#articles", expect_type=ListView)
        list_view.focus()
        list_view.action_cursor_down()

    def action_next_category(self) -> None:
        """Move to next category."""
        list_view: ListView = self.query_one(selector="#categories", expect_type=ListView)
        list_view.focus()
        if self.first_view:
            self.first_view = False
        else:
            list_view.index = self.category_index
        list_view.action_cursor_down()

    def action_open_original_article(self) -> None:
        """Open the original article in a web browser."""
        if hasattr(self, 'current_article_url') and self.current_article_url:
            webbrowser.open(self.current_article_url)
        else:
            print("No article selected or no URL available.")

    def action_previous_article(self) -> None:
        """Open previous article."""
        self.last_key = "k"
        list_view: ListView = self.query_one(selector="#articles", expect_type=ListView)
        list_view.focus()
        if not list_view.index == 0 or (self.group_feeds and list_view.index == 1):
            list_view.action_cursor_up()

    def action_previous_category(self) -> None:
        """Move to previous category."""
        list_view: ListView = self.query_one(selector="#categories", expect_type=ListView)
        list_view.focus()
        if self.first_view:
            self.first_view = False
        else:
            list_view.index = self.category_index
        list_view.action_cursor_up()

    async def action_recently_read(self) -> None:
        """Open recently read articles."""
        self.show_special_categories = True
        self.last_key = "R"
        await self.refresh_categories()

    async def action_refresh(self) -> None:
        """Refresh categories and articles from the server."""
        await self.refresh_categories()
        await self.refresh_articles()

    async def action_toggle_category(self) -> None:
        """Set expand category."""
        self.expand_category = not self.expand_category
        await self.refresh_categories()

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
        """Toggle article read and unread."""
        if hasattr(self, 'article_id') and self.article_id:
            client.toggle_unread(article_id=self.article_id)
        else:
            print("No article selected or no article_id available.")

    async def action_toggle_special_categories(self) -> None:
        """Toggle special categories."""
        self.show_special_categories = not self.show_special_categories
        self.last_key = "S"
        article_list: ListView = self.query_one(selector="#articles", expect_type=ListView)
        article_list.clear()
        await self.refresh_categories()

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"

    def action_toggle_star(self) -> None:
        """Toggle article (un)starred."""
        if hasattr(self, 'article_id') and self.article_id:
            client.toggle_starred(article_id=self.article_id)
        else:
            print("No article selected or no article_id available")

    async def action_toggle_unread(self) -> None:
        """Toggle unread-only mode and update category labels."""
        self.show_unread_only = not self.show_unread_only
        await self.refresh_categories()
        await self.refresh_articles()

    def action_view_source(self) -> None:
        """View markdown source."""
        if isinstance(self.screen, FullScreenTextArea):
            self.pop_screen()
        else:
            self.push_screen(screen=FullScreenTextArea(text=str(self.content_markdown)))

    async def display_article_content(self, article_id: int) -> None:
        """Fetch, clean, and display the selected article's content."""
        try:
            # Fetch the full article
            articles: list[Article] = client.get_articles(article_id=article_id)
        except Exception as err:
            print(f"Error fetching article content: {err}")

        if articles:
            article: Article = articles[0]

            # Parse and clean the HTML
            soup = BeautifulSoup(markup=article.content, features="html.parser")
            self.current_article_url = article.link

            self.content_markdown: str = markdownify(str(soup)).replace('xml encoding="UTF-8"', "")

            # Display the cleaned content
            content_view: LinkableMarkdownViewer = self.query_one(selector="#content", expect_type=LinkableMarkdownViewer)
            content_view.document.update(markdown=self.content_markdown)

            client.mark_read(article_id=article_id)
            await self.refresh_categories()
        else:
            print(f"No article found with ID {article_id}")

    async def refresh_articles(self, show_id=None) -> None:
        """Load articles from selected category or all articles."""
        if self.show_special_categories:
            view_mode = 'all_articles'
        else:
            view_mode = 'unread' if self.show_unread_only else 'all_articles'

        if not isinstance(show_id, int) and not show_id is None and show_id.startswith("feed_"):
            feed_id = int(show_id.replace("feed_", ""))
            is_cat = False
        elif show_id is not None:
            feed_id = show_id
            is_cat = True
        else:
            feed_id = -4
            is_cat = False

        try:
            list_view: ListView = self.query_one(selector="#articles", expect_type=ListView)
            await list_view.clear()

            articles: list[Headline] = client.get_headlines(feed_id=feed_id, is_cat=is_cat, view_mode=view_mode)
            feed_title: str = ""
            for article in articles:
                if self.group_feeds and article.feed_title and feed_title != article.feed_title:
                    feed_title = article.feed_title
                    feed_title_item = ListItem(Static(content=html.unescape(feed_title)), id=f"ft_{article.feed_id}")
                    feed_title_item.styles.color = "white"
                    feed_title_item.styles.background = "blue"
                    list_view.append(item=feed_title_item)
                style = "bold" if article.unread else "none"
                title = ListItem(Static(content=html.unescape(article.title)), id=f"art_{article.id}")
                title.styles.text_style = style
                list_view.append(item=title)
            if not articles:
                await self.action_clear()
        except Exception as err:
            print(f"Error fetching articles: {err}")

    async def refresh_categories(self) -> None:
        """Load categories from TTRSS and filter based on unread-only mode."""
        existing_ids: list[str] = []

        # Get all categories
        categories: list[Category] = client.get_categories()

        # Listview for categories and clear it
        list_view: ListView = self.query_one(selector="#categories", expect_type=ListView)
        await list_view.clear()

        unread_only: bool = False if self.show_special_categories else True
        max_length: int = 0

        if not categories is None:
            for category in sorted(categories, key=lambda x: x.title):
                # Skip categories with no unread articles if unread-only mode is enabled and special categories are hidden
                if not self.show_special_categories and self.show_unread_only and category.unread == 0:
                    continue

                # category_id is used if expand_category is enabled
                category_id: str = f"cat_{category.id}"

                # Top-level categories
                if category_id not in existing_ids:
                    # Handle view special categories
                    if (self.show_special_categories and category.title == "Special"):
                        article_count: str = f" ({category.unread})" if category.unread else ""
                        max_length = max(max_length, len(category.title))
                        list_view.append(item=ListItem(Static(content=category.title + article_count), id=category_id))
                    # Handle normal categories
                    elif (not self.show_special_categories and category.title != "Special"):
                        article_count: str = f" ({category.unread})" if category.unread else ""
                        max_length = max(max_length, len(category.title))
                        list_view.append(item=ListItem(Static(content=category.title + article_count), id=category_id))
                    else:
                        article_count = ""
                    existing_ids.append(category_id)

                # Expand category view to show feeds or show special categories (always expanded)
                if (self.expand_category and self.category_id == category_id and not self.show_special_categories) or (self.show_special_categories and category.title == "Special"):
                    feeds: list[Feed] = client.get_feeds(cat_id=category.id, unread_only=unread_only)
                    for feed in feeds:
                        feed_id: str = f"feed_{feed.id}"
                        if feed_id not in existing_ids:
                            feed_unread_count: str = f" ({feed.unread})" if feed.unread else ""
                            max_length = max(max_length, len(feed.title) + 3)
                            list_view.append(item=ListItem(Static(content="  " + feed.title + feed_unread_count), id=feed_id))
                            existing_ids.append(feed_id)
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

if __name__ == "__main__":
    app = ttcli()
    app.run()
