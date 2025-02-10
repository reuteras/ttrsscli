"""Command line tool to access Tiny Tiny RSS."""
import html
from math import e
import subprocess
import webbrowser
from typing import Any, ClassVar

import toml
from bs4 import BeautifulSoup
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Header, ListItem, ListView, MarkdownViewer, Static
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
            raise RuntimeError(f"Error executing command '{op_command}': {err}") from err
        except FileNotFoundError as err:
            raise RuntimeError("Error: 'op' command not found. Ensure 1Password CLI is installed and accessible.") from err
        except NameResolutionError as err:
            raise RuntimeError("Error: Couldn't look up server for url.") from err
    else:
        return op_command

# Load configuration
try:
    config: dict[str, Any] = toml.load("config.toml")
    api_url: str = get_conf_value(op_command=config["ttrss"].get("api_url", ""))
    username: str = get_conf_value(op_command=config["ttrss"].get("username", ""))
    password: str = get_conf_value(op_command=config["ttrss"].get("password", ""))
except (FileNotFoundError, toml.TomlDecodeError) as err:
    raise RuntimeError(f"Error reading configuration file: {err}") from err

# Connect to TTRSS
try:
    client = TTRClient(url=api_url, user=username, password=password, auto_login=True)
    client.login()
except TTRNotLoggedIn as err:
    raise RuntimeError("Error: Could not log in to Tiny Tiny RSS. Check your credentials.") from err


class HelpScreen(Screen):
    """A modal help screen."""

    def compose(self) -> ComposeResult:
        """Define the content layout of the help screen."""
        yield MarkdownViewer(
            markdown="""## TTRSS TUI Help
- **q**: Quit
- **h / H**: Show Help
- **u**: Toggle Unread Only
- **o**: Open Article in Browser
- **r**: Mark Read/Unread
- **s**: Star Article
- **,** : Refresh
- **tab / shift+tab**: Navigate Panes
""",
            id="fullscreen-content",
            show_table_of_contents=False
        )

class ttcli(App):
    """A Textual app to access Tiny Tiny RSS."""
    SCREENS: ClassVar[dict[str, type[Screen]]] = {
        "help": HelpScreen,
    }
    CSS_PATH: str = "styles.tcss"
    START_TEXT: str = "Welcome to TTRSS TUI!"
    article_id: int = 0
    category_id = None
    category_index: int = 0
    current_article_url = None
    expand_category: bool = False
    first_view: bool = True
    group_feeds: bool = False
    last_key: str = ""
    show_unread_only = reactive(default=True)
    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("?", "toggle_help", "Help"),
        ("c", "clear", "Clear"),
        ("comma", "refresh", "Refresh"),
        ("g", "toggle_feeds", "Group feeds"),
        ("h", "toggle_help", "Help"),
        ("H", "toggle_help", "Help"),
        ("J", "next_category", "Next category"),
        ("j", "next_article", "Next article"),
        ("K", "previous_category", "Previous category"),
        ("k", "previous_article", "Previous article"),
        ("m", "screen.maximize", "Maximize"),
        ("M", "screen.minimize", "Minimize"),
        ("n", "next_article", "Next article"),
        ("o", "open_original_article", "Open article in browser"),
        ("q", "quit", "Quit"),
        ("r", "toggle_read", "Mark Read/Unread"),
        ("e", "toggle_category", "Toggle category selection"),
        ("s", "toggle_star", "Star article"),
        ("shift+tab", "focus_previous_pane", "Previous pane"),
        ("tab", "focus_next_pane", "Next pane"),
        ("u", "toggle_unread", "Show categories with unread articles"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the layout."""
        yield Header(show_clock=True, name="ttcli")
        with Horizontal():
            yield ListView(id="categories")
            with Vertical():
                yield ListView(id="articles")
                yield MarkdownViewer(id="content", show_table_of_contents=False, markdown=self.START_TEXT)
        yield Footer()

    async def on_mount(self) -> None:
        """Fetch and display categories on startup."""
        await self.refresh_categories()

        categories: list[Category] = client.get_categories()
        max_length: int = max(len(category.title) for category in categories) # type: ignore
        estimated_width: int = max_length + 2
        categories_list: ListView = self.query_one(selector="#categories", expect_type=ListView)
        categories_list.styles.width = f"{estimated_width}"

    async def action_clear(self) -> None:
        """Clear content window."""
        self.article_id = 0
        content_view: MarkdownViewer = self.query_one(selector="#content", expect_type=MarkdownViewer)
        content_view.document.update(markdown=self.START_TEXT)

    async def action_toggle_feeds(self) -> None:
        """Toggle feed grouping."""
        self.group_feeds = not self.group_feeds
        await self.refresh_articles()

    async def action_refresh(self) -> None:
        """Refresh categories and articles from the server."""
        await self.refresh_categories()
        await self.refresh_articles()

    async def action_next_category(self) -> None:
        """Move to next category."""
        list_view: ListView = self.query_one(selector="#categories", expect_type=ListView)
        list_view.focus()
        if self.first_view:
            self.first_view = False
        else:
            list_view.index = self.category_index
        list_view.action_cursor_down()

    async def action_previous_category(self) -> None:
        """Move to previous category."""
        list_view: ListView = self.query_one(selector="#categories", expect_type=ListView)
        list_view.focus()
        if self.first_view:
            self.first_view = False
        else:
            list_view.index = self.category_index
        list_view.action_cursor_up()

    async def action_next_article(self) -> None:
        """Open next article."""
        self.last_key = "j"
        list_view: ListView = self.query_one(selector="#articles", expect_type=ListView)
        list_view.focus()
        list_view.action_cursor_down()

    async def action_previous_article(self) -> None:
        """Open previous article."""
        self.last_key = "k"
        list_view: ListView = self.query_one(selector="#articles", expect_type=ListView)
        list_view.focus()
        if not list_view.index == 0 or :
            list_view.action_cursor_up()
        list_view.action_cursor_up()

    async def refresh_categories(self) -> None:
        """Load categories from TTRSS and filter based on unread-only mode."""
        categories: list[Category] = client.get_categories()
        list_view: ListView = self.query_one(selector="#categories", expect_type=ListView)
        await list_view.clear()
        existing_ids: list[str] = []
        if not categories is None:
            for category in sorted(categories, key=lambda x: x.title):
                if self.show_unread_only and category.unread == 0:
                    continue
                unread_count: str = f" ({category.unread})" if category.unread else ""
                category_id: str = f"cat_{category.id}"
                if category_id not in existing_ids:
                    list_view.append(item=ListItem(Static(content=category.title + unread_count), id=category_id))
                    existing_ids.append(category_id)
                if self.category_id == category_id and self.expand_category:
                    feeds: list[Feed] = client.get_feeds(cat_id=category.id, unread_only=True)
                    for feed in feeds:
                        feed_id: str = f"feed_{feed.id}"
                        if feed_id not in existing_ids:
                            feed_unread_count: str = f" ({feed.unread})" if feed.unread else ""
                            list_view.append(item=ListItem(Static(content="  " + feed.title + feed_unread_count), id=feed_id))
                            existing_ids.append(feed_id)


    async def action_toggle_category(self) -> None:
        """Set expand category."""
        self.expand_category = not self.expand_category
        await self.refresh_categories()

    async def on_list_view_highlighted(self, message: Message) -> None:
        """Called when an item is highlighted in the ListView."""
        highlighted_item = message.item

        if highlighted_item:
            if highlighted_item.id.startswith("cat_"):  # Handle category selection
                category_id = int(highlighted_item.id.replace("cat_", ""))
                self.category_id = highlighted_item.id
                self.category_index = highlighted_item.parent.index
                await self.refresh_articles(show_id=category_id)
            elif highlighted_item.id.startswith("feed_"):  # Handle feed selection
                await self.refresh_articles(show_id=highlighted_item.id)
            elif highlighted_item.id.startswith("ft_"):  # Handle feed title selection
                if self.last_key == "j":
                    await self.action_next_article()
                elif self.last_key == "k":
                    if highlighted_item.parent.index == 0:
                        await self.action_next_article()
                    else:
                        await self.action_previous_article()
            elif highlighted_item.id.startswith("art_"):  # Handle article selection
                article_id = int(highlighted_item.id.replace("art_", ""))
                self.article_id: int = article_id
                highlighted_item.styles.text_style = "none"
                await self.display_article_content(article_id=article_id)

    async def on_list_view_selected(self, message: Message) -> None:
        """Called when an item is selected in the ListView."""
        selected_item = message.item

        if selected_item:
            if selected_item.id.startswith("cat_"):  # Handle category selection
                category_id = int(selected_item.id.replace("cat_", ""))
                await self.refresh_articles(show_id=category_id)

            elif selected_item.id.startswith("art_"):  # Handle article selection
                article_id = int(selected_item.id.replace("art_", ""))
                self.article_id = article_id
                selected_item.styles.text_style = "none"
                await self.display_article_content(article_id=article_id)

    async def display_article_content(self, article_id: int) -> None:
        """Fetch, clean, and display the selected article's content."""
        try:
            # Fetch the full article
            articles: list[Article] = client.get_articles(article_id=article_id)
            if articles:
                article: Article = articles[0]

                # Parse and clean the HTML
                soup = BeautifulSoup(markup=article.content, features="html.parser")
                self.current_article_url = article.link

                # Extract text while keeping relevant formatting
                for a in soup.find_all(name="a"):  # Make links clickable
                    a.string = f"[{a.get_text()}]({a['href']})"

                clean_content = soup.get_text(separator="\n\n", strip=True)

                # Display the cleaned content
                content_view: MarkdownViewer = self.query_one(selector="#content", expect_type=MarkdownViewer)
                content_view.document.update(markdown=clean_content)

                # Mark the article as read on the server
                client.mark_read(article_id=article_id)

                # Refresh categories to update unread counts
                await self.refresh_categories()

            else:
                print(f"No article found with ID {article_id}")

        except Exception as err:
            print(f"Error fetching article content: {err}")

    async def action_open_original_article(self) -> None:
        """Open the original article in a web browser."""
        if hasattr(self, 'current_article_url') and self.current_article_url:
            webbrowser.open(self.current_article_url)
        else:
            print("No article selected or no URL available.")

    async def action_toggle_read(self) -> None:
        """Toggle article read and unread."""
        if hasattr(self, 'article_id') and self.article_id:
            client.toggle_unread(article_id=self.article_id)
        else:
            print("No article selected or no article_id available.")

    async def refresh_articles(self, show_id=None) -> None:
        """Load articles from selected category or all articles."""
        view_mode = 'unread'
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
                if self.group_feeds and feed_title != article.feed_title:
                    feed_title = article.feed_title
                    feed_title_item = ListItem(Static(content=html.unescape(feed_title)), id=f"ft_{article.feed_id}")
                    feed_title_item.styles.color = "white"
                    feed_title_item.styles.background = "blue"
                    list_view.append(item=feed_title_item)
                style = "bold" if article.unread else "none"
                title = ListItem(Static(content=html.unescape(article.title)), id=f"art_{article.id}")
                title.styles.text_style = style
                list_view.append(item=title)
        except Exception as err:
            print(f"Error fetching articles: {err}")

    async def action_toggle_help(self) -> None:
        """Toggle the help screen."""
        if isinstance(self.screen, HelpScreen):
            self.pop_screen()
        else:
            self.push_screen(screen=HelpScreen())

    async def action_toggle_unread(self) -> None:
        """Toggle unread-only mode and update category labels."""
        self.show_unread_only = not self.show_unread_only
        await self.refresh_categories()
        await self.refresh_articles()

    async def action_focus_next_pane(self) -> None:
        """Move focus to the next pane."""
        panes: list[str] = ["categories", "articles", "content"]
        current_focus: Widget | None = self.focused
        if current_focus:
            current_id: str | None = current_focus.id
            if current_id in panes:
                next_index: int = (panes.index(current_id) + 1) % len(panes)
                next_pane: Widget = self.query_one(selector=f"#{panes[next_index]}")
                next_pane.focus()
                next_pane.index = self.category_index

    async def action_focus_previous_pane(self) -> None:
        """Move focus to the previous pane."""
        panes: list[str] = ["categories", "articles", "content"]
        current_focus: Widget | None = self.focused
        if current_focus:
            current_id: str | None = current_focus.id
            if current_id in panes:
                previous_index: int = (panes.index(current_id) - 1) % len(panes)
                previous_pane: Widget = self.query_one(selector=f"#{panes[previous_index]}")
                previous_pane.focus()
                previous_pane.index = self.category_index

if __name__ == "__main__":
    app = ttcli()
    app.run()
