"""Simplified terminal image widget for Textual."""

import base64
import io
import logging
import sys
from pathlib import Path

from PIL import Image
from rich.text import Text
from rich_pixels import Pixels  # Use rich-pixels instead of custom rendering
from textual.widget import Widget

from ttrsscli.ui.rich_widgets import detect_terminal
from ttrsscli.utils.terminal_graphics import TerminalType

logger = logging.getLogger(name=__name__)


class TerminalImage(Widget):
    """A widget that renders an image using rich-pixels for compatibility."""

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
        self.pixels = None
        self.terminal_type: TerminalType = detect_terminal()
        self.use_native_protocols = True
        
        # Load the image
        self._load_image()

    def _load_image(self) -> None:
        """Load and prepare the image data for rendering."""
        try:
            # Check if file exists
            if not self.image_path.exists():
                logger.error(f"Image file not found: {self.image_path}")
                self.renderable = None
                return
            
            # Open the image
            img = Image.open(self.image_path)
            logger.debug(f"Loaded image {self.image_path}: mode={img.mode}, size={img.size}")
            
            # Convert to RGB if needed
            if img.mode == 'RGBA':
                bg = Image.new('RGB', img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            elif img.mode != 'RGB':
                img = img.convert('RGB')
                
            # For iTerm2/Kitty with native protocols enabled, prepare high quality image
            if self.use_native_protocols and self.terminal_type in (TerminalType.ITERM2, TerminalType.KITTY):
                # Use larger size for high quality
                orig_size = img.size
                img.thumbnail((self.max_width * 10, self.max_height * 10))
                logger.debug(f"Resized image for native rendering: {orig_size} -> {img.size}")
                
                # Store dimensions
                self.width, self.height = img.size
                
                # Prepare base64 data
                with io.BytesIO() as buf:
                    img.save(buf, format='PNG')
                    image_data = buf.getvalue()
                self.b64_data = base64.b64encode(image_data).decode('ascii')
                b64_len = len(self.b64_data)
                logger.debug(f"Prepared image data: {b64_len} bytes encoded")
                
                # Mark for native rendering
                self.renderable = "native"
                logger.debug(f"Using native rendering for {self.image_path}")
            else:
                # For other terminals, use rich-pixels
                orig_size = img.size
                img.thumbnail((self.max_width, self.max_height))
                logger.debug(f"Resized image for rich-pixels: {orig_size} -> {img.size}")
                self.renderable = Pixels.from_image(img)
                logger.debug(f"Using rich-pixels rendering for {self.image_path}")
                
        except Exception as e:
            logger.error(f"Error loading image {self.image_path}: {e}")
            self.renderable = None

def render(self):
    """Render the image.
    
    Returns:
        Rich renderable object
    """
    if not hasattr(self, 'renderable') or self.renderable is None:
        return Text(f"[Image Error: {self.image_path.name}]")
    
    if self.renderable == "native":
        # Create appropriate escape sequence based on terminal type
        if self.terminal_type == TerminalType.ITERM2:
            # iTerm2 inline image protocol
            escape_seq = f"\033]1337;File=inline=1;width={self.width}px;height={self.height}px:{self.b64_data}\007"
            logger.debug(f"iTerm2 protocol: image size={self.width}x{self.height}, seq_len={len(escape_seq)}")
            # Return as Text with a display placeholder, but the escape sequence will be processed by terminal
            result = Text("📊")  # Use a placeholder character that will be replaced by the image
            result._text = escape_seq  # Set the raw text to be the escape sequence
            return result
        elif self.terminal_type == TerminalType.KITTY:
            # Kitty graphics protocol
            escape_seq = f"\033_Ga=T,f=100,s={self.width},v={self.height}:{self.b64_data}\033\\"
            logger.debug(f"Kitty protocol: image size={self.width}x{self.height}, seq_len={len(escape_seq)}")
            result = Text("📊")
            result._text = escape_seq
            return result
        else:
            # Fallback to text if somehow we got here with an unsupported terminal
            logger.warning(f"Native rendering requested but terminal {self.terminal_type} not supported")
            return Text(f"[Image: {self.image_path.name}]")
    else:
        # Return the rich-pixels renderable
        return self.renderable


class DirectTerminalImage(Widget):
    """Directly renders terminal images by writing to stdout."""

    DEFAULT_CSS = """
    DirectTerminalImage {
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
        """Initialize the direct terminal image widget.

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
        self.rendered = False
        
        # Detect terminal type
        self.terminal_type = detect_terminal()
        logger.debug(f"DirectTerminalImage using: {self.terminal_type}")

    async def on_mount(self) -> None:
        """When widget is mounted, render image directly to terminal."""
        self.render_direct()

    def render_direct(self) -> None:
        """Render image directly to the terminal."""
        if self.rendered:
            return
            
        try:
            # Only proceed for supported terminals
            if self.terminal_type not in (TerminalType.ITERM2, TerminalType.KITTY):
                logger.warning(f"Terminal {self.terminal_type} doesn't support native graphics")
                return
                
            # Check if file exists
            if not self.image_path.exists():
                logger.error(f"Image file not found: {self.image_path}")
                return
                
            # Open the image
            img = Image.open(self.image_path)
            
            # Convert to RGB if needed
            if img.mode == 'RGBA':
                bg = Image.new('RGB', img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            elif img.mode != 'RGB':
                img = img.convert('RGB')
                
            # Use larger size for high quality
            orig_size = img.size
            img.thumbnail((self.max_width * 10, self.max_height * 10))
            logger.debug(f"Direct rendering: Resized image: {orig_size} -> {img.size}")
            
            # Get dimensions
            width, height = img.size
            
            # Prepare base64 data
            with io.BytesIO() as buf:
                img.save(buf, format='PNG')
                image_data = buf.getvalue()
            b64_data = base64.b64encode(image_data).decode('ascii')
            
            # Get appropriate escape sequence
            if self.terminal_type == TerminalType.ITERM2:
                # iTerm2 inline image protocol
                escape_seq = f"\033]1337;File=inline=1;width={width}px;height={height}px:{b64_data}\007"
            elif self.terminal_type == TerminalType.KITTY:
                # Kitty graphics protocol
                escape_seq = f"\033_Ga=T,f=100,s={width},v={height}:{b64_data}\033\\"
            else:
                return
                
            # Print escape sequence directly to terminal
            # This bypasses Textual's rendering system completely
            logger.debug(f"Direct rendering: Outputting {len(escape_seq)} bytes to terminal")
            sys.stdout.write(escape_seq)
            sys.stdout.flush()
            
            # Mark as rendered
            self.rendered = True
            
        except Exception as e:
            logger.error(f"Error in direct rendering: {e}")

    def render(self):
        """Render a placeholder for Textual's rendering system."""
        # We've already done the real rendering directly,
        # so just return a placeholder for Textual
        height = 1
        if self.terminal_type in (TerminalType.ITERM2, TerminalType.KITTY) and self.rendered:
            # Reserve space equivalent to image height
            height = max(1, min(self.max_height // 2, 10))
            
        # Return empty lines to reserve space
        lines = []
        for _ in range(height):
            lines.append("")
            
        return Text("\n".join(lines))