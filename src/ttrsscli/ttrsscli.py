"""Command line tool to access Tiny Tiny RSS."""

import argparse
import functools
import html
import os
import subprocess
import sys
import webbrowser
from collections import OrderedDict
from collections.abc import Generator
from datetime import datetime
from importlib import metadata
from time import sleep
from typing import Any, ClassVar, Literal
from urllib.parse import quote

import httpx
import toml
from bs4 import BeautifulSoup
from cleanurl import Result, cleanurl
from markdownify import markdownify
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import (
    Footer,
    Header,
    Label,
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


class LimitedSizeDict(OrderedDict):
    """A dictionary that holds at most 'max_size' items and removes the oldest when full."""

    def __init__(self, max_size: int) -> None:
        """Initialize the LimitedSizeDict."""
        self.max_size: int = max_size
        super().__init__()

    def __setitem__(self, key, value) -> None:
        """Set an item in the dictionary, removing the oldest if full."""
        if key in self:
            self.move_to_end(key=key)
        super().__setitem__(key, value)
        if len(self) > self.max_size:
            self.popitem(last=False)


# Helper function to retrieve credentials from 1Password CLI or return the value directly
def get_conf_value(op_command: str) -> str:
    """Get the configuration value from 1Password if config starts with 'op '."""
    if op_command.startswith("op "):
        try:
            result: subprocess.CompletedProcess[str] = subprocess.run(
                op_command.split(), capture_output=True, text=True, check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as err:
            print(f"Error executing command '{op_command}': {err}")
            sys.exit(1)
        except FileNotFoundError:
            print(
                "Error: 'op' command not found. Ensure 1Password CLI is installed and accessible."
            )
            sys.exit(1)
        except NameResolutionError:
            print("Error: Couldn't look up server for url.")
            sys.exit(1)
    else:
        return op_command


# Decorator to handle session expiration - had trouble with auto_login=True in ttrss-python
def handle_session_expiration(api_method):
    """Decorator that retries a function call after re-authenticating if session expires."""

    @functools.wraps(wrapped=api_method)
    def wrapper(self, *args, **kwargs) -> Any:
        try:
            return api_method(self, *args, **kwargs)
        except ConnectionResetError as err:
            if "ConnectionResetError" in str(object=err):
                sleep(1)
                # Re-login
                if not self.login():
                    raise RuntimeError("Re-authentication failed") from err

                # Retry the original function call
                return api_method(self, *args, **kwargs)
        except Exception as err:
            if "NOT_LOGGED_IN" in str(object=err):
                # Re-login
                if not self.login():
                    raise RuntimeError("Re-authentication failed") from err

                # Retry the original function call
                return api_method(self, *args, **kwargs)
            raise err

    return wrapper


class TTRSSClient:
    """A wrapper for ttrss-python to reauthenticate on failure."""

    def __init__(self, url, username, password) -> None:
        """Initialize the TTRSS client."""
        self.url: str = url
        self.username: str = username
        self.password: str = password
        self.api = TTRClient(
            url=self.url, user=self.username, password=self.password, auto_login=False
        )
        self.login()

    def login(self) -> bool:
        """Authenticate with TTRSS and store session."""
        try:
            self.api.login()
            return True
        except Exception:
            return False

    @handle_session_expiration
    def get_articles(self, article_id) -> list[Article]:
        """Fetch article content, retrying if session expires."""
        return self.api.get_articles(article_id=article_id)

    @handle_session_expiration
    def get_categories(self) -> list[Category]:
        """Fetch category list, retrying if session expires."""
        return self.api.get_categories()

    @handle_session_expiration
    def get_feeds(self, cat_id, unread_only) -> list[Feed]:
        """Fetch feed list, retrying if session expires."""
        return self.api.get_feeds(cat_id=cat_id, unread_only=unread_only)

    @handle_session_expiration
    def get_headlines(self, feed_id, is_cat, view_mode) -> list[Headline]:
        """Fetch headlines for a feed, retrying if session expires."""
        return self.api.get_headlines(
            feed_id=feed_id, is_cat=is_cat, view_mode=view_mode
        )

    @handle_session_expiration
    def mark_read(self, article_id) -> None:
        """Mark article as read, retrying if session expires."""
        self.api.mark_read(article_id=article_id)

    @handle_session_expiration
    def mark_unread(self, article_id) -> None:
        """Mark article as unread, retrying if session expires."""
        self.api.mark_unread(article_id=article_id)

    @handle_session_expiration
    def toggle_starred(self, article_id) -> None:
        """Toggle article starred, retrying if session expires."""
        self.api.toggle_starred(article_id=article_id)

    @handle_session_expiration
    def toggle_unread(self, article_id) -> None:
        """Toggle article read/unread, retrying if session expires."""
        self.api.toggle_unread(article_id=article_id)


class Configuration:
    """A class to handle configuration values."""

    def __init__(self, arguments) -> None:
        """Initialize the configuration."""
        # Use argparse and to add arguments
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
            "--version", dest="version", type=bool, help="Show version", default=False
        )
        args: argparse.Namespace = arg_parser.parse_args(args=arguments)

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
            self.download_folder: str = get_conf_value(
                op_command=self.config["general"].get("download_folder", "")
            )
            self.readwise_token: str = get_conf_value(
                op_command=self.config["readwise"].get("token", "")
            )
            self.obsidian_vault: str = get_conf_value(
                op_command=self.config["obsidian"].get("vault", "")
            )
            self.obsidian_folder: str = get_conf_value(
                op_command=self.config["obsidian"].get("folder", "")
            )
            self.obsidian_default_tag: str = get_conf_value(
                op_command=self.config["obsidian"].get("default_tag", "")
            )
            self.obsidian_include_tags: bool = self.config["obsidian"].get(
                "include_tags", "False"
            )
            self.obsidian_include_labels: bool = self.config["obsidian"].get(
                "include_labels", "True"
            )
            self.obsidian_template: str = get_conf_value(
                op_command=self.config["obsidian"].get("template", "")
            )
            self.version: str = metadata.version(distribution_name="ttrsscli")
        except KeyError as err:
            print(f"Error reading configuration: {err}")
            sys.exit(1)

    def load_config_file(self, config_file: str) -> dict[str, Any]:
        """Load the configuration from the TOML file."""
        try:
            return toml.load(f=config_file)
        except (FileNotFoundError, toml.TomlDecodeError) as err:
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


# Textual Screen classes
class LinkSelectionScreen(ModalScreen):
    """Modal screen to show extracted links and allow selection."""

    def __init__(self, configuration, links, open_links="browser", open=False) -> None:
        """Initialize the link selection screen."""
        """
        links: list of tuples with link title and URL
        open_links:
            - "browser" to open link in browser
            - "download" to save link to download folder
            - "readwise" to save link to Readwise
        """
        super().__init__()
        self.links: Any = links
        self.open_links: str = open_links
        self.open: bool = open
        self.configuration: Configuration = configuration

    def compose(self) -> ComposeResult:
        """Define the content layout of the link selection screen."""
        if self.open_links == "browser":
            yield Label(renderable="Select a link to open (ESC to go back):")
        elif self.open_links == "download":
            yield Label(renderable="Select a link to download (ESC to go back):")
        elif self.open_links == "readwise":
            yield Label(
                renderable="Select a link to save to Readwise (ESC to go back):"
            )
        link_select = ListView(
            *[
                ListItem(Label(renderable=f"{link[0]}\n{link[1]}"))
                for link in self.links
            ]
        )
        # Longest link title or link URL
        longest_link: int = 0
        for link in self.links:
            longest_link = max(longest_link, len(link[0]), len(link[1]))
        link_select.styles.align_horizontal = "left"
        link_select.styles.width = longest_link + 5
        link_select.styles.max_width = "100%"
        yield link_select

    def download_file(self, link: str) -> None:
        """Download a file from the given URL and save to download folder."""
        try:
            with httpx.Client() as http_client:
                httpx_response: httpx.Response = http_client.get(
                    url=link, follow_redirects=True
                )
        except Exception as err:
            self.notify(
                title="Download",
                message=f"Error downloading {link}. Error {err}",
                timeout=5,
                severity="error",
            )

        if httpx_response.status_code == httpx.codes.OK:
            try:
                filename: str = httpx_response.url.path.split(sep="/")[-1]
            except Exception:
                filename = "index.dat"
            filename = "index.dat" if filename == "" else filename

            # Save the file to the download folder
            try:
                with open(
                    file=os.path.join(self.configuration.download_folder, filename),
                    mode="wb",
                ) as file:
                    file.write(httpx_response.content)
            except Exception:
                self.notify(
                    title="Download",
                    message=f"Error saving {filename}.",
                    timeout=5,
                    severity="error",
                )
            self.notify(title="Saved", message=f"Saved {filename}.", timeout=5)
        else:
            self.notify(
                title="Download",
                message=f"Error downloading {link}. Status code {httpx_response.status_code}.",
                timeout=5,
                severity="error",
            )

    def on_key(self, event) -> None:
        """Close the full-screen Markdown viewer on any key press."""
        if event.key in ALLOW_IN_FULL_SCREEN:
            pass
        else:
            self.app.pop_screen()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Open the selected link in the browser."""
        link: str = self.links[event.list_view.index][1]
        if self.open_links == "browser":
            webbrowser.open(url=link)
        elif self.open_links == "download":
            self.download_file(link=link)
        elif self.open_links == "readwise":
            if not self.configuration.readwise_token:
                self.notify(
                    title="Readwise",
                    message="No Readwise token found.",
                    timeout=5,
                    severity="warning",
                )
            else:
                try:
                    os.environ["READWISE_TOKEN"] = self.configuration.readwise_token
                    import readwise
                    from readwise.model import PostResponse

                    response: tuple[bool, PostResponse] = readwise.save_document(
                        url=link
                    )
                except Exception as err:
                    self.notify(
                        title="Readwise",
                        message=f"Error saving url {link}. Error {err}",
                        timeout=5,
                        severity="error",
                    )
                if response[1].url and response[1].id:
                    self.notify(
                        title="Readwise", message=f"Url {link} saved.", timeout=5
                    )
                else:
                    self.notify(
                        title="Readwise",
                        message=f"Error saving url {link}.",
                        timeout=5,
                        severity="error",
                    )
                if self.open:
                    webbrowser.open(url=response[1].url)
        self.app.pop_screen()


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
        yield LinkableMarkdownViewer(
            markdown=self.markdown_content, show_table_of_contents=True
        )

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
- **d**: Toggle dark and light mode
- **v**: Show version

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
- **u**: Show all categories (include unread)

## Links

Project home: [https://github.com/reuteras/ttcli](https://github.com/reuteras/ttcli)

For more about Tiny Tiny RSS, see the [Tiny Tiny RSS website](https://tt-rss.org/). Tiny Tiny RSS is not affiliated with this project.
""",
            id="fullscreen-content",
            show_table_of_contents=False,
            open_links=False,
        )


# Main Textual App class
class ttrsscli(App[None]):
    """A Textual app to access and read articles from Tiny Tiny RSS."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("?", "toggle_help", "Help"),
        ("C", "toggle_clean_url", "Toggle clean urls with cleanurl"),
        ("c", "clear", "Clear"),
        ("comma", "refresh", "Refresh"),
        ("ctrl+l", "readwise_article_url", "Add link in article to later app"),
        (
            "ctrl+shift+l",
            "readwise_article_url_and_open",
            "Add link in article to later app",
        ),
        ("ctrl+o", "open_article_url", "Open article urls"),
        ("ctrl+s", "save_article_url", "Save link to download folder"),
        ("d", "toggle_dark", "Toggle dark mode"),
        ("e", "toggle_category", "Toggle category selection"),
        ("G", "refresh", "Refresh"),
        ("g", "toggle_feeds", "Group feeds"),
        ("H", "toggle_header", "Header"),
        ("h", "toggle_help", "Help"),
        ("J", "next_category", "Next category"),
        ("j", "next_article", "Next article"),
        ("K", "previous_category", "Previous category"),
        ("k", "previous_article", "Previous article"),
        ("l", "add_to_later_app", "Add to later app"),
        ("L", "add_to_later_app_and_open", "Add to later app and open"),
        ("M", "view_markdown_source", "View md source"),
        ("m", "maximize_content", "Maximize content pane"),
        ("n", "next_article", "Next article"),
        ("O", "export_to_obsidian", "Export to Obsidian"),
        ("o", "open_original_article", "Open article in browser"),
        ("q", "quit", "Quit"),
        ("R", "recently_read", "Open recently read articles"),
        ("r", "toggle_read", "Mark Read/Unread"),
        ("S", "toggle_special_categories", "Show special categories"),
        ("s", "toggle_star", "Star article"),
        ("shift+tab", "focus_previous_pane", "Previous pane"),
        ("tab", "focus_next_pane", "Next pane"),
        ("u", "toggle_unread", "Show categories with unread articles"),
        ("v", "show_version", "Show version"),
    ]
    SCREENS: ClassVar[dict[str, type[Screen]]] = {
        "help": HelpScreen,
    }
    CSS_PATH: str = "styles.tcss"

    def __init__(self) -> None:
        """Connect to Tiny Tiny RSS and initialize the app."""
        try:
            # Load the configuration via the Configuration class sending it command line arguments
            configuration = Configuration(arguments=sys.argv[1:])
            self.client = TTRSSClient(
                url=configuration.api_url,
                username=configuration.username,
                password=configuration.password,
            )
        except TTRNotLoggedIn:
            print("Error: Could not log in to Tiny Tiny RSS. Check your credentials.")
            sys.exit(1)
        except NameResolutionError:
            print("Error: Couldn't look up server for url.")
            sys.exit(1)

        self.START_TEXT: str = (
            "Welcome to ttcli TUI! A text-based interface to Tiny Tiny RSS."
        )
        # State variables

        # Current article ID
        self.article_id: int = 0
        # Current category ID
        self.category_id = None
        # Current category index position
        self.category_index: int = 0
        # Should urls be cleaned with cleanurl?
        self.clean_url: bool = True
        # Configuration
        self.configuration: Configuration = configuration
        # Content pane markdown content
        self.content_markdown: str = self.START_TEXT
        # Current article
        self.current_article: Article | None = None
        # Current article title
        self.current_article_title: str = ""
        # Current article URL (for opening in browser with 'o')
        self.current_article_url: str = ""
        # Expand category view to show feeds for selected category
        self.expand_category: bool = False
        # First view flag used when first started
        self.first_view: bool = True
        # Group articles by feed
        self.group_feeds: bool = True
        # Last key pressed (for j/k navigation)
        self.last_key: str = ""
        # Show header info for article
        self.show_header: bool = False
        # Show unread categories only
        self.show_unread_only = reactive(default=True)
        # Show special categories
        self.show_special_categories: bool = False
        # Tags for articles
        self.tags = LimitedSizeDict(max_size=10000)
        super().__init__()

    def compose(self) -> ComposeResult:
        """Compose the three pane layout."""
        yield Header(show_clock=True, name="ttcli")
        with Horizontal():
            yield ListView(id="categories")
            with Vertical():
                yield ListView(id="articles")
                yield LinkableMarkdownViewer(
                    id="content", show_table_of_contents=False, markdown=self.START_TEXT
                )
        yield Footer()

    async def on_list_view_highlighted(self, message: Message) -> None:
        """Called when an item is highlighted in the ListViews (both categories and articles)."""
        highlighted_item: Any = message.item  # type: ignore
        try:
            if not highlighted_item is None:
                # Handle category selection -> refresh articles
                if highlighted_item.id.startswith("cat_"):
                    category_id = int(highlighted_item.id.replace("cat_", ""))
                    self.category_id = highlighted_item.id
                    await self.refresh_articles(show_id=category_id)
                    # Update category index position for navigation
                    if hasattr(highlighted_item, "parent") and hasattr(
                        highlighted_item.parent, "index"
                    ):
                        self.category_index = highlighted_item.parent.index

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
        except Exception as err:
            print(f"Error handling list view highlight: {err}")

    async def on_list_view_selected(self, message: Message) -> None:
        """Called when an item is selected in the ListViews (both category and article)."""
        selected_item: Any = message.item  # type: ignore

        try:
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
        except Exception as err:
            print(f"Error handling list view selection: {err}")

    async def on_mount(self) -> None:
        """Fetch and display categories on startup."""
        await self.refresh_categories()
        await self.refresh_articles()

    def action_add_to_later_app(self, open=False) -> None:
        """Add article to later app."""
        if not self.configuration.readwise_token:
            self.notify(
                title="Readwise",
                message="No Readwise token found.",
                timeout=5,
                severity="warning",
            )
        elif hasattr(self, "current_article_url") and self.current_article_url:
            os.environ["READWISE_TOKEN"] = self.configuration.readwise_token
            import readwise
            from readwise.model import PostResponse

            try:
                response: tuple[bool, PostResponse] = readwise.save_document(
                    url=self.current_article_url
                )
            except Exception as err:
                self.notify(
                    title="Readwise",
                    message=f"Error saving url {self.current_article_url}. Error {err}",
                    timeout=5,
                    severity="error",
                )
            if response[1].url and response[1].id:
                self.notify(
                    title="Readwise",
                    message=f"Url {self.current_article_url} saved.",
                    timeout=5,
                )
                if open:
                    webbrowser.open(url=response[1].url)
            else:
                self.notify(
                    title="Readwise",
                    message=f"Error saving url {self.current_article_url}.",
                    timeout=5,
                    severity="error",
                )
        else:
            self.notify(
                title="Readwise",
                message="No article selected or no URL available.",
                timeout=5,
                severity="warning",
            )

    def action_add_to_later_app_and_open(self) -> None:
        """Add article to later app and open that Readwise page in browser."""
        self.action_add_to_later_app(open=True)

    async def action_clear(self) -> None:
        """Clear content window."""
        self.content_markdown = self.START_TEXT

        # Reset article variables
        self.current_article_title = ""
        self.current_article_url = ""
        self.current_article_urls: list[Any] = []

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

    def action_export_to_obsidian(self) -> None:
        """Send the current content as a new note to Obsidian via URI scheme."""
        # Documentation for Obsidian URI scheme: https://help.obsidian.md/Extending+Obsidian/Obsidian+URI

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
        content = content.replace("<ID>", datetime.now().strftime(format="%Y%m%d%H%M "))
        content = content.replace("<CONTENT>", self.content_markdown_original)
        content = content.replace("<TITLE>", self.current_article_title)
        tags = self.configuration.obsidian_default_tag + "  \n"
        article_labels = ""
        article_tags = ""
        if self.show_header and self.configuration.obsidian_include_labels:
            try:
                article_labels: str = (
                    f"  - {', '.join(item[1] for item in self.current_article.labels)}"  # type: ignore
                )
            except AttributeError:
                article_labels = ""
        if self.show_header and self.configuration.obsidian_include_tags:
            try:
                article_tags: str = "\n".join(
                    f"  - {item}"
                    for item in self.tags[self.current_article.id]  # type: ignore
                )
            except KeyError:
                article_tags = ""
        tags += article_labels + article_tags
        content = content.replace("<TAGS>", tags)
        content = content.replace("  - \n", "")
        content = content.replace("\n\n", "\n")

        # Encode title and content for URL format
        encoded_title: str = quote(string=title).replace("/", "%2F")
        encoded_content: str = quote(string=content)

        # Construct the Obsidian URI
        obsidian_uri: str = f"obsidian://new?vault={self.configuration.obsidian_vault}&file={encoded_title}&content={encoded_content}"

        # Open the Obsidian URI (this will create or update the note)
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
        elif list_view.index is None:
            list_view.index = 1
            self.category_index = 1
        else:
            list_view.index = self.category_index
        list_view.action_cursor_down()

    def action_open_original_article(self) -> None:
        """Open the original article in a web browser."""
        if hasattr(self, "current_article_url") and self.current_article_url:
            webbrowser.open(url=self.current_article_url)
        else:
            self.notify(
                message="No article selected or no URL available.", title="Info"
            )

    async def action_open_article_url(self):
        """Open links from the article in a web browser."""
        if hasattr(self, "current_article_urls") and self.current_article_urls:
            self.push_screen(
                screen=LinkSelectionScreen(
                    configuration=self.configuration, links=self.current_article_urls
                )
            )
        else:
            self.notify(message="No links found!", title="Info")

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
        elif list_view.index == 0:
            pass
        else:
            list_view.index = self.category_index
        list_view.action_cursor_up()

    async def action_recently_read(self) -> None:
        """Open recently read articles."""
        self.show_special_categories = True
        self.last_key = "R"
        await self.refresh_categories()

    def action_readwise_article_url(self) -> None:
        """Add one article link to later app."""
        if hasattr(self, "current_article_url") and self.current_article_urls:
            self.push_screen(
                screen=LinkSelectionScreen(
                    configuration=self.configuration,
                    links=self.current_article_urls,
                    open_links="readwise",
                )
            )
        else:
            self.notify(
                title="Readwise",
                message="No article selected or no URLs available.",
                timeout=5,
                severity="warning",
            )

    def action_readwise_article_url_and_open(self) -> None:
        """Add one article link to later app."""
        if hasattr(self, "current_article_url") and self.current_article_urls:
            self.push_screen(
                screen=LinkSelectionScreen(
                    configuration=self.configuration,
                    links=self.current_article_urls,
                    open_links="readwise",
                    open=True,
                )
            )
        else:
            self.notify(
                title="Readwise",
                message="No article selected or no URLs available.",
                timeout=5,
                severity="warning",
            )

    async def action_refresh(self) -> None:
        """Refresh categories and articles from the server."""
        await self.refresh_categories()
        await self.refresh_articles()

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
                message="No article selected or no URLs available.",
                timeout=5,
                severity="warning",
            )

    def action_show_version(self) -> None:
        """Show version."""
        self.notify(
            title="Info",
            message=f"Version: {self.configuration.version}",
            timeout=5,
            severity="information",
        )

    async def action_toggle_category(self) -> None:
        """Set expand category."""
        self.expand_category = not self.expand_category
        await self.refresh_categories()

    def action_toggle_clean_url(self) -> None:
        """Clean urls."""
        self.clean_url = not self.clean_url
        if self.clean_url:
            self.notify(message="Clean urls enabled.", title="Info")
        else:
            self.notify(message="Clean urls disabled.", title="Info")

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.theme = (
            "textual-dark" if self.theme == "textual-light" else "textual-light"
        )

    async def action_toggle_header(self) -> None:
        """Toggle header info for article."""
        self.show_header = not self.show_header
        self.client.mark_unread(article_id=self.current_article.id)  # type: ignore
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
        """Toggle article read and unread."""
        if hasattr(self, "article_id") and self.article_id:
            self.client.toggle_unread(article_id=self.article_id)
        else:
            self.notify(
                title="Article",
                message="No article selected or no article_id available.",
                timeout=5,
                severity="error",
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
        """Toggle article (un)starred."""
        if hasattr(self, "article_id") and self.article_id:
            self.client.toggle_starred(article_id=self.article_id)
        else:
            self.notify(
                title="Article",
                message="No article selected or no article_id available.",
                timeout=5,
                severity="error",
            )

    async def action_toggle_unread(self) -> None:
        """Toggle unread-only mode and update category labels."""
        self.show_unread_only = not self.show_unread_only
        await self.refresh_categories()
        await self.refresh_articles()

    def action_view_markdown_source(self) -> None:
        """View markdown source."""
        if isinstance(self.screen, FullScreenTextArea):
            self.pop_screen()
        else:
            self.push_screen(screen=FullScreenTextArea(text=str(self.content_markdown)))

    async def display_article_content(self, article_id: int) -> None:
        """Fetch, clean, and display the selected article's content."""
        try:
            # Fetch the full article
            articles: list[Article] = self.client.get_articles(article_id=article_id)
        except Exception as err:
            self.notify(
                title="Article",
                message=f"Error fetching article content: {err}",
                timeout=5,
                severity="error",
            )

        if articles:
            try:
                article: Article = articles[0]
            except Exception:
                self.notify(
                    title="Article",
                    message=f"No article found with ID {article_id}.",
                    timeout=5,
                    severity="error",
                )

            self.current_article = article

            # Parse and clean the HTML
            soup = BeautifulSoup(markup=article.content, features="html.parser")  # type: ignore
            self.current_article_url: str = self.get_clean_url(url=article.link)  # type: ignore
            self.current_article_title: str = article.title  # type: ignore

            # Add document urls to list
            self.current_article_urls = []
            for a in soup.find_all(name="a"):
                try:
                    self.current_article_urls.append(
                        (a.get_text(), self.get_clean_url(url=a["href"]))  # type: ignore
                    )
                except KeyError:
                    pass
            self.content_markdown_original: str = markdownify(
                html=str(object=soup)
            ).replace('xml encoding="UTF-8"', "")

            header: str = self.get_header(article=article)

            self.content_markdown = header + self.content_markdown_original

            # Display the cleaned content
            content_view: LinkableMarkdownViewer = self.query_one(
                selector="#content", expect_type=LinkableMarkdownViewer
            )
            content_view.document.update(markdown=self.content_markdown)

            self.client.mark_read(article_id=article_id)
            await self.refresh_categories()

    def get_clean_url(self, url: str) -> str:
        """Clear url."""
        if self.clean_url:
            cleaned_url: Result | None = cleanurl(url=url)
            if cleaned_url:
                return cleaned_url.url
            else:
                return url
        else:
            return url

    def get_header(self, article: Article) -> str:
        """Get header info for article."""
        header: str = ""
        if self.show_header:
            header = f"> **Title:** {self.current_article_title}  \n"
            header += f"> **URL:** {self.current_article_url}  \n"
            if hasattr(article, "author") and article.author:  # type: ignore
                header += f"> **Author:** {article.author}  \n"  # type: ignore
            if hasattr(article, "published") and article.published:  # type: ignore
                header += f"> **Published:** {article.published}  \n"  # type: ignore
            if hasattr(article, "updated") and article.updated:
                header += f"> **Updated:** {article.updated}  \n"  # type: ignore
            if hasattr(article, "note") and article.note:  # type: ignore
                header += f"> **Note:** {article.note}  \n" if article.note else ""  # type: ignore
            if hasattr(article, "feed_title") and article.feed_title:  # type: ignore
                header += (
                    f"> **Feed:** {article.feed_title}  \n"  # type: ignore
                    if article.feed_title  # type: ignore
                    else ""
                )
            try:
                header += f"> **Labels:** {', '.join(item[1] for item in article.labels) if article.labels else ''}  \n"  # type: ignore
            except AttributeError:
                pass
            try:
                header += (
                    f"> **Tags:** {', '.join(self.tags[article.id])}  \n"  # type: ignore
                    if len(self.tags[article.id][0]) > 0  # type: ignore
                    else ""
                )
            except KeyError:
                pass
            if hasattr(article, "tags") and article.tags:  # type: ignore
                header += f"> **Tags:** {article.tags}  \n" if article.tags else ""  # type: ignore
            if hasattr(article, "lang") and article.lang:  # type: ignore
                header += f"> **Language:** {article.lang}  \n" if article.lang else ""  # type: ignore
            if hasattr(article, "marked") and article.marked:  # type: ignore
                header += (
                    f"> **Starred:** {article.marked}  \n" if article.marked else ""  # type: ignore
                )  # type: ignore
            header += "  \n"
        return header

    async def refresh_articles(self, show_id=None) -> None:
        """Load articles from selected category or all articles."""
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
            feed_title: str = ""
            for article in articles:
                self.tags[article.id] = article.tags  # type: ignore
                prepend: str = ""
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
                if article.title != "":  # type: ignore
                    article_id = f"art_{article.id}"  # type: ignore
                    if article_id not in article_ids:
                        style: str = "bold" if article.unread else "none"  # type: ignore
                        if article.note or article.published or article.marked:  # type: ignore
                            prepend = "("
                            prepend += "N" if article.note else ""  # type: ignore
                            if article.published:  # type: ignore
                                prepend += "P" if prepend == "(" else ", P"
                            if article.marked:  # type: ignore
                                prepend += "S" if prepend == "(" else ", S"
                            prepend += ") "
                        article_title: str = html.unescape(
                            prepend + article.title.strip()  # type: ignore
                        )
                        article_title_item = ListItem(
                            Static(content=article_title), id=article_id
                        )
                        article_title_item.styles.text_style = style
                        list_view.append(item=article_title_item)
                        article_ids.append(article_id)
            if not articles:
                await self.action_clear()
        except Exception as err:
            self.notify(
                title="Articles",
                message=f"Error fetching articles: {err}",
                timeout=5,
                severity="error",
            )

    async def refresh_categories(self) -> None:
        """Load categories from TTRSS and filter based on unread-only mode."""
        existing_ids: list[str] = []

        # Get all categories
        categories: list[Category] = self.client.get_categories()

        # Listview for categories and clear it
        list_view: ListView = self.query_one(
            selector="#categories", expect_type=ListView
        )
        await list_view.clear()

        unread_only: bool = False if self.show_special_categories else True
        max_length: int = 0

        if not categories is None:
            for category in sorted(categories, key=lambda x: x.title):  # type: ignore
                # Skip categories with no unread articles if unread-only mode is enabled and special categories are hidden
                if (
                    not self.show_special_categories
                    and self.show_unread_only
                    and category.unread == 0  # type: ignore
                ):
                    continue

                # category_id is used if expand_category is enabled
                category_id: str = f"cat_{category.id}"  # type: ignore

                # Top-level categories
                if category_id not in existing_ids:
                    # Handle view special categories
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
                        )  # type: ignore
                    # Handle normal categories
                    elif (
                        not self.show_special_categories and category.title != "Special"  # type: ignore
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
                    else:
                        article_count = ""
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
                                        content="  " + feed.title + feed_unread_count  # type: ignore
                                    ),
                                    id=feed_id,
                                )
                            )
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


def main() -> None:
    """Run the ttcli app."""
    app = ttrsscli()
    app.run()


def main_web() -> None:
    """Run the ttcli app in web mode."""
    from textual_serve.server import Server

    app = Server(command="ttrsscli")
    app.serve()


if __name__ == "__main__":
    app = ttrsscli()
    app.run()
