"""Rich-based widgets for ttrsscli."""

import logging
import webbrowser

from rich.markdown import Markdown
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import Click
from textual.geometry import Region
from textual.scroll_view import ScrollView
from textual.widgets import Static

from ..utils.rich_markdown import RichMarkdownRenderer

logger: logging.Logger = logging.getLogger(name=__name__)


class ClickableText(Text):
    """Rich Text that tracks hyperlinks and supports click events."""

    def __init__(self, *args, **kwargs) -> None:
        """Initialize clickable text."""
        super().__init__(*args, **kwargs)
        self.hyperlinks: dict[str, str] = {}
        
    def add_link(self, text: str, url: str) -> None:
        """Add a link to the text.
        
        Args:
            text: Link text to display
            url: URL the link points to
        """
        start: int = len(self)
        self.append(text=text)
        end: int = len(self)
        
        self.stylize(style=f"link {url}", start=start, end=end)
        self.hyperlinks[url] = text
        
    def get_link_at(self, x: int) -> str:
        """Get URL at the given position if it exists.
        
        Args:
            x: X-coordinate in the text
            
        Returns:
            URL or None if no link at position
        """
        for span in self.spans:
            style = span[1]
            if hasattr(style, "meta") and style.meta: # type: ignore
                if "link" in style.meta: # type: ignore
                    link_url: str = style.meta["link"] # type: ignore
                    span_range: int = span[0]
                    if span_range.start <= x < span_range.end: # type: ignore
                        return link_url
                        
        return ""


class RichMarkdownView(ScrollView):
    """A markdown viewer that uses Rich for rendering."""

    DEFAULT_CSS = """
    RichMarkdownView {
        background: $surface;
        color: $text;
        border: none;
        padding: 0 1;
    }
    
    RichMarkdownView > .markdown-container {
        width: 1fr;
        height: auto;
    }
    """
    
    BINDINGS = [  # noqa: RUF012
        Binding(key="up", action="scroll_up", description="Scroll Up", show=False),
        Binding(key="down", action="scroll_down", description="Scroll Down", show=False),
        Binding(key="home", action="scroll_home", description="Scroll Home", show=False),
        Binding(key="end", action="scroll_end", description="Scroll End", show=False),
        Binding(key="page_up", action="page_up", description="Page Up", show=False),
        Binding(key="page_down", action="page_down", description="Page Down", show=False),
    ]

    def __init__(
        self,
        markdown: str = "",
        *,
        name = None,
        id = None,
        classes = None,
    ) -> None:
        """Initialize the Rich markdown viewer.
        
        Args:
            markdown: Initial markdown content
            name: Widget name
            id: Widget ID
            classes: CSS classes
        """
        super().__init__(name=name, id=id, classes=classes)
        
        self._content: str = markdown
        
        # Keep track of clickable areas
        self.link_regions: dict[Region, str] = {}
        self.hover_link: str = ""
        
        # Set up renderer
        self.markdown_renderer = RichMarkdownRenderer()
        
    def compose(self) -> ComposeResult:
        """Define the layout of the markdown viewer."""
        yield Static(id="markdown-container", expand=True)

    async def on_mount(self) -> None:
        """Set up the widget when mounted."""
        # Initial render of content
        await self.update(markdown=self._content)

    async def update(self, markdown: str) -> None:
        """Update the markdown content.
        
        Args:
            markdown: New markdown content to display
        """
        self._content = markdown
        
        # Extract links for click handling
        self.links = self.markdown_renderer.extract_links(markdown_text=markdown)
        
        # Render the markdown content
        markdown_container: Static = self.query_one(selector="#markdown-container", expect_type=Static)
        rich_md: Markdown = self.markdown_renderer.render_markdown(markdown_text=markdown)
        await markdown_container.update(content=rich_md)

    async def on_click(self, event: Click) -> None:
        """Handle click events to support hyperlinks.
        
        Args:
            event: Click event
        """
        # Get the position relative to the content
        screen_x: int = event.screen_x
        screen_y: int = event.screen_y
        rel_y: int = screen_y - self.region.y - self.scroll_offset.y
        rel_x: int = screen_x - self.region.x
        
        # Check if we're clicking on a link
        for region, url in self.link_regions.items():
            if region.contains_point(point=(rel_x, rel_y)):
                await self._handle_link_click(url=url)
                break

    async def _handle_link_click(self, url: str) -> None:
        """Handle a click on a link.
        
        Args:
            url: URL to open
        """
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.error(msg=f"Error opening URL {url}: {e}")
            self.notify(
                message=f"Error opening URL: {e}",
                title="Link Error",
                severity="error"
            )

    def clear(self) -> None:
        """Clear the content."""
        self._content = ""
        self.link_regions = {}