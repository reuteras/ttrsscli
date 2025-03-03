"""Terminal graphics support for high-quality images.

This module provides support for various terminal graphics protocols:
- iTerm2 inline images
- Kitty graphics protocol 
- Sixel graphics
- Unicode half-blocks (fallback)
"""

import base64
import io
import logging
import os
from enum import Enum, auto
from pathlib import Path

from PIL import Image

logger = logging.getLogger(name=__name__)

class TerminalType(Enum):
    """Terminal types with graphics support."""
    UNKNOWN = auto()
    ITERM2 = auto()
    KITTY = auto()
    SIXEL = auto()
    UNICODE = auto()
    BLOCK = auto()
    NONE = auto()

def detect_terminal() -> TerminalType:
    """Detect the terminal type and graphics capabilities.
    
    Returns:
        TerminalType enum indicating terminal graphics support
    """
    term = os.environ.get("TERM", "").lower()
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    colorterm = os.environ.get("COLORTERM", "").lower()
    
    # Check for iTerm2
    if term_program == "iterm.app":
        return TerminalType.ITERM2
    
    # Check for Kitty
    if term == "xterm-kitty":
        return TerminalType.KITTY
    
    # Check for terminals with sixel support
    if "sixel" in term:
        return TerminalType.SIXEL
    
    # Check for terminals with at least truecolor support
    if "truecolor" in colorterm:
        return TerminalType.UNICODE
    
    # Minimal block graphics support
    if "256color" in term:
        return TerminalType.BLOCK
        
    return TerminalType.NONE

class TerminalGraphics:
    """Handler for rendering images using terminal graphics protocols."""
    
    def __init__(self, 
                 max_width: int = 80, 
                 max_height: int = 20,
                 preserve_aspect_ratio: bool = True,
                 prefer_protocol = None):
        """Initialize terminal graphics handler.
        
        Args:
            max_width: Maximum image width in terminal cells
            max_height: Maximum image height in terminal cells
            preserve_aspect_ratio: Whether to preserve image aspect ratio
            prefer_protocol: Preferred terminal protocol to use, or None for auto-detect
        """
        self.max_width = max_width
        self.max_height = max_height
        self.preserve_aspect_ratio = preserve_aspect_ratio
        
        # Detect or use preferred terminal type
        self.terminal_type = prefer_protocol or detect_terminal()
        logger.debug(f"Using terminal graphics protocol: {self.terminal_type}")
        
        # Scaling factors for different terminals
        # Some terminals have non-square character cells
        self.width_scale = 1.0
        self.height_scale = 2.0  # For UNICODE mode, each block is 2 cells high

    def render_image(self, image_path: Path) -> str:
        """Render an image using the best available terminal protocol.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            String containing terminal escape sequences for displaying the image
        """
        try:
            img = Image.open(image_path)
            
            # Convert to RGB if necessary (remove alpha channel)
            if img.mode == 'RGBA':
                bg = Image.new('RGB', img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            elif img.mode != 'RGB':
                img = img.convert('RGB')
                
            # Resize image to fit terminal constraints
            img = self._resize_image(img)
            
            # Render using the best available method
            if self.terminal_type == TerminalType.ITERM2:
                return self._render_iterm2(img)
            elif self.terminal_type == TerminalType.KITTY:
                return self._render_kitty(img)
            elif self.terminal_type == TerminalType.SIXEL:
                return self._render_sixel(img)
            elif self.terminal_type == TerminalType.UNICODE:
                return self._render_unicode(img)
            else:
                return self._render_block(img)
        except Exception as e:
            logger.error(f"Error rendering image {image_path}: {e}")
            return f"[Image: {image_path.name}]"

    def _resize_image(self, img: Image.Image) -> Image.Image:
        """Resize image to fit terminal constraints.
        
        Args:
            img: Pillow Image object
            
        Returns:
            Resized Pillow Image object
        """
        # Get original dimensions
        orig_width, orig_height = img.size
        
        # Calculate new dimensions based on terminal constraints
        # and scaling factors for terminal cell aspect ratio
        term_width = int(self.max_width / self.width_scale)
        term_height = int(self.max_height / self.height_scale)
        
        if self.preserve_aspect_ratio:
            # Calculate scaling factor to fit within constraints
            width_ratio = term_width / orig_width
            height_ratio = term_height / orig_height
            ratio = min(width_ratio, height_ratio)
            
            new_width = int(orig_width * ratio)
            new_height = int(orig_height * ratio)
        else:
            new_width = term_width
            new_height = term_height
        
        # Don't resize if image is already smaller than constraints
        if new_width >= orig_width and new_height >= orig_height:
            return img
            
        # Resize the image with high quality
        return img.resize((new_width, new_height), Image.LANCZOS)

    def _render_iterm2(self, img: Image.Image) -> str:
        """Render image using iTerm2 inline image protocol.
        
        Args:
            img: Pillow Image object
            
        Returns:
            String with iTerm2 escape sequences
        """
        # Save image to bytes
        with io.BytesIO() as buf:
            img.save(buf, format='PNG')
            image_data = buf.getvalue()
        
        # Encode in base64
        b64_data = base64.b64encode(image_data).decode('ascii')
        
        # Format iTerm2 escape sequence
        width, height = img.size
        return f"\033]1337;File=inline=1;width={width}px;height={height}px:{b64_data}\a"

    def _render_kitty(self, img: Image.Image) -> str:
        """Render image using Kitty graphics protocol.
        
        Args:
            img: Pillow Image object
            
        Returns:
            String with Kitty escape sequences
        """
        # Save image to bytes
        with io.BytesIO() as buf:
            img.save(buf, format='PNG')
            image_data = buf.getvalue()
        
        # Encode in base64
        b64_data = base64.b64encode(image_data).decode('ascii')
        
        # Format Kitty escape sequence
        # This is a simplified version of the protocol
        return f"\033_Ga=T,f=100,s={img.width},v={img.height}:{b64_data}\033\\"

    def _render_sixel(self, img: Image.Image) -> str:
        """Render image using Sixel graphics protocol.
        
        Args:
            img: Pillow Image object
            
        Returns:
            String with Sixel escape sequences
        """
        # For sixel, we'd need a proper sixel encoder
        # This is a placeholder - in a real implementation, you'd use
        # the libsixel Python bindings or another Sixel library
        return f"[Sixel image: {img.width}x{img.height}]"

    def _render_unicode(self, img: Image.Image) -> str:
        """Render image using Unicode half-block characters.
        
        Args:
            img: Pillow Image object
            
        Returns:
            String with Unicode characters representing the image
        """
        width, height = img.size
        
        # Ensure even height for half-blocks
        if height % 2 == 1:
            height = height + 1
            img_resized = Image.new('RGB', (width, height), (0, 0, 0))
            img_resized.paste(img, (0, 0))
            img = img_resized
        
        # Get pixel data
        pixels = list(img.getdata())
        pixels = [pixels[i * width:(i + 1) * width] for i in range(height)]
        
        result = []
        # Process pixels two rows at a time for half-blocks
        for y in range(0, height, 2):
            line = ""
            for x in range(width):
                if y + 1 >= height:
                    # If we're at the last row and it's odd, use a single block
                    upper = pixels[y][x]
                    line += self._rgb_to_halfblock(upper, upper)
                else:
                    upper = pixels[y][x]
                    lower = pixels[y + 1][x]
                    line += self._rgb_to_halfblock(upper, lower)
            result.append(line)
        
        return "\n".join(result)

    def _rgb_to_halfblock(self, upper_rgb: tuple[int, int, int], 
                          lower_rgb: tuple[int, int, int]) -> str:
        """Convert a pair of RGB values to a half-block character with ANSI colors.
        
        Args:
            upper_rgb: RGB values for upper half (0-255 per channel)
            lower_rgb: RGB values for lower half (0-255 per channel)
            
        Returns:
            String with ANSI color codes and half-block character
        """
        # Unicode half-block (upper half)
        block = "▀"
        
        # Convert RGB to ANSI 24-bit color escape sequences
        ur, ug, ub = upper_rgb
        lr, lg, lb = lower_rgb
        
        # Background is lower half, foreground is upper half
        fg = f"\033[38;2;{ur};{ug};{ub}m"
        bg = f"\033[48;2;{lr};{lg};{lb}m"
        
        # Reset code
        reset = "\033[0m"
        
        return f"{fg}{bg}{block}{reset}"

    def _render_block(self, img: Image.Image) -> str:
        """Render image using simple block characters for limited terminals.
        
        Args:
            img: Pillow Image object
            
        Returns:
            String with block characters representing the image
        """
        # Downscale the image much more for block mode
        new_width = min(img.width, self.max_width // 2)
        ratio = new_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((new_width, new_height), Image.LANCZOS)
        
        # Convert to grayscale
        img = img.convert('L')
        
        # Get pixel data
        pixels = list(img.getdata())
        pixels = [pixels[i * new_width:(i + 1) * new_width] for i in range(new_height)]
        
        # Define block characters for different brightness levels
        blocks = " .:-=+*#%@"
        
        result = []
        for row in pixels:
            line = ""
            for pixel in row:
                # Map grayscale value (0-255) to block character index (0-9)
                idx = min(9, pixel // 28)
                line += blocks[idx]
            result.append(line)
        
        return "\n".join(result)