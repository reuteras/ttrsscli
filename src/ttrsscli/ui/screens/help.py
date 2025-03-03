"""Help screen for ttrsscli."""

from textual.app import ComposeResult
from textual.screen import Screen

from ..widgets import ALLOW_IN_FULL_SCREEN, LinkableMarkdownViewer


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