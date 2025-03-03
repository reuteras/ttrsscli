"""Custom widget for displaying terminal images in Textual."""

import base64
import io
import logging
import os
from pathlib import Path

from PIL import Image
from rich.console import RenderResult
from rich.segment import Segment, Segments
from rich.style import Style
from rich.text import Text
from textual.widget import Widget

from ..utils.terminal_graphics import TerminalGraphics, TerminalType, detect_terminal

logger = logging.getLogger(name=__name__)


class TerminalImage(Widget):
    """A widget that renders an image using terminal graphics protocols."""

    DEFAULT_CSS = """
    TerminalImage {
        width: auto;
        height: auto;
        padding: 0;
        margin: 0 1;
    }
    """

    def __init__(  # noqa: PLR0913
        self,
        image_path: Path,
        *,
        max_width: int = 80,
        max_height: int = 24,
        name = None,
        id = None,
        classes = None,
    ) -> None:
        """Initialize the terminal image widget.

        Args:
            image_path: Path to the image file
            max_width: Maximum width for the image
            max_height: Maximum height for the image
            name: Widget name
            id: Widget ID
            classes: CSS classes
        """
        super().__init__(name=name, id=id, classes=classes)
        self.image_path = image_path
        self.max_width = max_width
        self.max_height = max_height
        
        # Detect terminal for later rendering
        self.terminal_type = detect_terminal()
        logger.debug(f"Terminal image: detected terminal type = {self.terminal_type}")
        
        # Default to UNICODE for more compatibility in Textual apps
        if self.terminal_type in (TerminalType.ITERM2, TerminalType.KITTY):
            # Check if we're running in a Textual environment
            # In that case, fall back to Unicode rendering for better compatibility
            if "TEXTUAL" in os.environ or "RICH_CONSOLE" in os.environ:
                logger.debug(f"Running in Textual, falling back to UNICODE rendering instead of {self.terminal_type}")
                self.terminal_type = TerminalType.UNICODE
        
        self.graphics = TerminalGraphics(
            max_width=max_width,
            max_height=max_height,
            prefer_protocol=self.terminal_type
        )
        
        # Prepare image data
        self._prepare_image()

    def _prepare_image(self) -> None:
        """Prepare the image data for rendering."""
        try:
            # Open and analyze the image
            self.img = Image.open(self.image_path)
            
            # Calculate dimensions based on terminal constraints
            self.img = self.graphics._resize_image(self.img)
            
            # Get original dimensions
            self.width, self.height = self.img.size
            
            # For iTerm2/Kitty, prepare the base64 data
            if self.terminal_type in (TerminalType.ITERM2, TerminalType.KITTY):
                with io.BytesIO() as buf:
                    self.img.save(buf, format='PNG')
                    image_data = buf.getvalue()
                self.b64_data = base64.b64encode(image_data).decode('ascii')
            
            # Get actual image content for different terminal types
            if self.terminal_type == TerminalType.UNICODE:
                # For Unicode half-blocks, convert to pixels once
                rgb_img = self.img.convert('RGB')
                self.pixels = list(rgb_img.getdata())
                self.pixels = [self.pixels[i * self.width:(i + 1) * self.width] 
                               for i in range(self.height)]
            elif self.terminal_type == TerminalType.BLOCK:
                # For block characters, convert to grayscale
                gray_img = self.img.convert('L')
                self.pixels = list(gray_img.getdata())
                self.pixels = [self.pixels[i * self.width:(i + 1) * self.width] 
                               for i in range(self.height)]
        except Exception as e:
            logger.error(f"Error preparing image {self.image_path}: {e}")
            # Set defaults for error state
            self.img = None
            self.width = 0
            self.height = 0
            self.pixels = []

    def render_line(self, y: int):  # noqa: PLR0911, PLR0912
        """Render a single line of the image.
        
        Args:
            y: Line number to render
            
        Returns:
            List of segments to render
        """
        if not self.img:
            return [Segment(f"[Image Error: {self.image_path.name}]")]
        
        try:
            # Handle different terminal types
            if self.terminal_type == TerminalType.ITERM2:
                # iTerm2 protocol - only output on first line
                if y == 0:
                    # Format the escape sequence
                    escape_seq = f"\x1b]1337;File=inline=1;width={self.width}px;height={self.height}px:{self.b64_data}\x07"
                    return [Segment(escape_seq)]
                else:
                    # Other lines are empty to make space for the image
                    return []
            
            elif self.terminal_type == TerminalType.KITTY:
                # Kitty protocol - only output on first line
                if y == 0:
                    # Format the escape sequence
                    escape_seq = f"\x1b_Ga=T,f=100,s={self.width},v={self.height}:{self.b64_data}\x1b\\"
                    return [Segment(escape_seq)]
                else:
                    # Other lines are empty to make space for the image
                    return []
            
            elif self.terminal_type == TerminalType.UNICODE:
                # Unicode half-blocks - process two rows at a time
                if y >= (self.height + 1) // 2 or not hasattr(self, 'pixels') or not self.pixels:
                    return []
                
                segments = []
                row_y = y * 2  # Each rendered line represents 2 pixel rows
                
                for x in range(self.width):
                    # Get upper pixel
                    upper = self.pixels[row_y][x]
                    
                    # Get lower pixel (if exists)
                    if row_y + 1 < self.height:
                        lower = self.pixels[row_y + 1][x]
                    else:
                        lower = upper  # Use upper pixel if at last row
                    
                    # Create a half-block with proper colors
                    ur, ug, ub = upper
                    lr, lg, lb = lower
                    
                    # Create rich-compatible style
                    fg_style = f"rgb({ur},{ug},{ub})"
                    bg_style = f"rgb({lr},{lg},{lb})"
                    style = Style(color=fg_style, bgcolor=bg_style)
                    
                    # Add segment with half-block character
                    segments.append(Segment("▀", style))
                
                return segments
            
            elif self.terminal_type == TerminalType.BLOCK:
                # Block characters for basic terminals
                if y >= self.height or not hasattr(self, 'pixels') or not self.pixels:
                    return []
                
                # Define block characters for different brightness levels
                blocks = " .:-=+*#%@"
                
                segments = []
                for x in range(self.width):
                    pixel = self.pixels[y][x]
                    # Map grayscale value (0-255) to block character
                    idx = min(9, pixel // 28)
                    segments.append(Segment(blocks[idx]))
                
                return segments
            
            else:
                # Fallback - just display image name
                if y == 0:
                    return [Segment(f"[Image: {self.image_path.name}]")]
                return []
                
        except Exception as e:
            logger.error(f"Error rendering line {y}: {e}")
            if y == 0:
                return [Segment(f"[Image Error: {e}]")]
            return []
            
    def render(self) -> RenderResult:  # noqa: PLR0912
        """Render the image widget.
        
        Returns:
            RenderResult containing renderable objects for each line
        """
        # For iTerm2 and Kitty, we just need a single line with the escape sequence
        if self.terminal_type in (TerminalType.ITERM2, TerminalType.KITTY):
            segments_for_line = self.render_line(0)
            if segments_for_line:
                yield Segments(segments_for_line)
            
            # Add empty lines to create space for the image
            for _ in range(1, (self.height + 1) // 2):
                yield Text("")
        
        # For Unicode, we need half as many lines as the image height
        elif self.terminal_type == TerminalType.UNICODE:
            for y in range((self.height + 1) // 2):
                segments_for_line = self.render_line(y)
                if segments_for_line:
                    yield Segments(segments_for_line)
                else:
                    yield Text("")
        
        # For block mode, we need as many lines as the image height
        elif self.terminal_type == TerminalType.BLOCK:
            for y in range(self.height):
                segments_for_line = self.render_line(y)
                if segments_for_line:
                    yield Segments(segments_for_line)
                else:
                    yield Text("")
        
        # Fallback
        else:
            segments_for_line = self.render_line(0)
            if segments_for_line:
                yield Segments(segments_for_line)
            else:
                yield Text(f"[Image: {self.image_path.name}]")