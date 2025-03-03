"""Rich-based widgets for ttrsscli."""

import logging
import webbrowser
from pathlib import Path

from rich.markdown import Markdown
from rich.text import Text
from rich_pixels import Pixels
from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import Click
from textual.geometry import Region
from textual.scroll_view import ScrollView
from textual.widgets import Static

from ..utils.image import ImageHandler
from ..utils.rich_markdown import RichMarkdownRenderer
from ..utils.terminal_graphics import TerminalType, detect_terminal
from .terminal_image import DirectTerminalImage, TerminalImage

logger = logging.getLogger(name=__name__)


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
        start = len(self)
        self.append(text)
        end = len(self)
        
        self.stylize(f"link {url}", start, end)
        self.hyperlinks[url] = text
        
    def get_link_at(self, x: int):
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
                    link_url = style.meta["link"] # type: ignore
                    span_range = span[0]
                    if span_range.start <= x < span_range.end: # type: ignore
                        return link_url
                        
        return None


class RichMarkdownView(ScrollView):
    """A markdown viewer that uses Rich for rendering with support for images."""

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
    
    RichMarkdownView > .image-container {
        width: 1fr;
        height: auto;
        margin: 1 0;
    }
    """
    
    BINDINGS = [  # noqa: RUF012
        Binding("up", "scroll_up", "Scroll Up", show=False),
        Binding("down", "scroll_down", "Scroll Down", show=False),
        Binding("home", "scroll_home", "Scroll Home", show=False),
        Binding("end", "scroll_end", "Scroll End", show=False),
        Binding("page_up", "page_up", "Page Up", show=False),
        Binding("page_down", "page_down", "Page Down", show=False),
    ]

    def __init__(  # noqa: PLR0913
        self,
        markdown: str = "",
        *,
        max_image_width: int = 80,
        max_image_height: int = 20,
        use_native_protocols: bool = True,
        name= None,
        id = None,
        classes = None,
    ) -> None:
        """Initialize the Rich markdown viewer.
        
        Args:
            markdown: Initial markdown content
            max_image_width: Maximum width for images
            max_image_height: Maximum height for images
            use_native_protocols: Whether to use native terminal graphics
            name: Widget name
            id: Widget ID
            classes: CSS classes
        """
        super().__init__(name=name, id=id, classes=classes)
        
        self._content: str = markdown
        self.max_image_width: int = max_image_width
        self.max_image_height: int = max_image_height
        self.use_native_protocols: bool = use_native_protocols
        
        # Log the configuration
        logger.debug(f"RichMarkdownView initialized with: max_width={max_image_width}, " +
                    f"max_height={max_image_height}, use_native_protocols={use_native_protocols}")
        
        # Keep track of clickable areas
        self.link_regions: dict[Region, str] = {}
        self.hover_link: str = ""
        
        # Set up renderers
        self.markdown_renderer = RichMarkdownRenderer()
        self.image_handler = ImageHandler(
            max_width=max_image_width,
            max_height=max_image_height,
            use_native_protocols=use_native_protocols
        )
        
        # Image cache for current view
        self.images = {}
        self.image_widgets = []

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
        
        # Process the markdown with our renderer
        clean_markdown, image_info = self.markdown_renderer.extract_images(markdown)
        
        # Extract links for click handling
        self.links = self.markdown_renderer.extract_links(clean_markdown)
        
        # Process any images
        if image_info:
            self.images = self.image_handler.process_images(image_info)
        else:
            self.images = {}
            
        # Render the markdown content
        markdown_container: Static = self.query_one(selector="#markdown-container", expect_type=Static)
        rich_md: Markdown = self.markdown_renderer.render_markdown(markdown_text=clean_markdown)
        await markdown_container.update(content=rich_md)
        
        # Render any images we found
        await self._render_images()
    
    async def _render_images(self) -> None:
        """Render images below the markdown content."""
        # Remove any existing image widgets
        for widget in self.image_widgets:
            try:
                if widget.mounted:
                    await widget.remove()
            except Exception as e:
                logger.error(f"Error removing image widget: {e}")
        self.image_widgets = []
        
        # Detect terminal type for making decisions
        terminal_type = detect_terminal()
        logger.debug(f"Rendering images with terminal type: {terminal_type}")
        
        # If we have images to display, create widgets for them
        for img_url, rendered in self.images.items():
            try:
                if isinstance(rendered, Path):
                    # Choose appropriate image widget based on terminal and settings
                    if (terminal_type in (TerminalType.ITERM2, TerminalType.KITTY) and 
                        self.use_native_protocols):
                        # Use direct rendering for iTerm2/Kitty with native graphics
                        logger.debug(f"Using DirectTerminalImage for {img_url}")
                        img_widget = DirectTerminalImage(
                            image_path=rendered,
                            max_width=self.max_image_width,
                            max_height=self.max_image_height,
                            classes="image-container"
                        )
                    else:
                        # Fall back to regular TerminalImage for other terminals
                        logger.debug(f"Using regular TerminalImage for {img_url}")
                        img_widget = TerminalImage(
                            image_path=rendered,
                            max_width=self.max_image_width,
                            max_height=self.max_image_height,
                            use_native_protocols=self.use_native_protocols,
                            classes="image-container"
                        )
                elif isinstance(rendered, Pixels):
                    # This is a Pixels object from rich-pixels
                    from textual.widgets import Static
                    img_widget = Static(rendered, classes="image-container")
                else:
                    # Fallback for any other case
                    from textual.widgets import Static
                    img_widget = Static(f"[Image: {img_url.split('/')[-1]}]", classes="image-container")
                
                # Mount the widget
                await self.mount(img_widget)
                self.image_widgets.append(img_widget)
            except Exception as e:
                logger.error(f"Error creating image widget for {img_url}: {e}")
                # Try to create a simple static widget as fallback
                try:
                    from textual.widgets import Static
                    fallback = Static(f"[Error displaying image: {e}]", classes="image-container")
                    await self.mount(fallback)
                    self.image_widgets.append(fallback)
                except Exception:
                    pass  # If even the fallback fails, just skip this image

    async def on_click(self, event: Click) -> None:
        """Handle click events to support hyperlinks.
        
        Args:
            event: Click event
        """
        # Get the position relative to the content
        screen_x, screen_y = event.screen_x, event.screen_y
        rel_y = screen_y - self.region.y - self.scroll_offset.y
        rel_x = screen_x - self.region.x
        
        # Check if we're clicking on a link
        for region, url in self.link_regions.items():
            if region.contains_point(rel_x, rel_y):
                await self._handle_link_click(url)
                break

    async def _handle_link_click(self, url: str) -> None:
        """Handle a click on a link.
        
        Args:
            url: URL to open
        """
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.error(f"Error opening URL {url}: {e}")
            self.notify(
                f"Error opening URL: {e}",
                title="Link Error",
                severity="error"
            )

    def clear(self) -> None:
        """Clear the content."""
        self._content = ""
        self.images = {}
        self.link_regions = {}