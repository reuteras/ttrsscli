"""Image processing utilities for ttrsscli using rich-pixels."""

import logging
import tempfile
from pathlib import Path

import httpx
from PIL import Image as PILImage
from rich_pixels import Pixels

from .terminal_graphics import TerminalGraphics

logger = logging.getLogger(name=__name__)


class ImageHandler:
    """Handler for fetching and processing images for terminal display."""

    def __init__(self, 
                 cache_dir = None, 
                 max_width: int = 100, 
                 max_height: int = 30,
                 prefer_terminal = None,
                 use_native_protocols: bool = True):
        """Initialize the image handler.

        Args:
            cache_dir: Directory to cache downloaded images (uses temp dir if None)
            max_width: Maximum display width for images
            max_height: Maximum display height for images
            prefer_terminal: Preferred terminal type to use
            use_native_protocols: Whether to use native terminal graphics protocols
        """
        self.http_client = httpx.Client(follow_redirects=True)
        
        # Set up cache directory
        if cache_dir:
            self.cache_dir = Path(cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.cache_dir = Path(tempfile.mkdtemp(prefix="ttrsscli_img_cache_"))
            
        self.max_width: int = max_width
        self.max_height: int = max_height
        self.image_cache: dict[str, Path] = {}  # URL to file path
        
        # Terminal graphics
        self.use_native_protocols = use_native_protocols
        if use_native_protocols:
            self.terminal_graphics = TerminalGraphics(
                max_width=max_width,
                max_height=max_height,
                prefer_protocol=prefer_terminal
            )
        
    def __del__(self):
        """Clean up resources."""
        try:
            self.http_client.close()
        except Exception:
            pass

    def fetch_image(self, url: str):
        """Fetch image from URL and return path to local file.
        
        Args:
            url: Image URL
            
        Returns:
            Path to local image file or None on failure
        """
        # Return cached image if available
        if url in self.image_cache:
            return self.image_cache[url]
        
        try:
            # Generate a filename from URL
            from urllib.parse import urlparse
            url_parts = urlparse(url)
            filename = Path(url_parts.path).name
            
            # If no filename, use the last part of path or a default
            if not filename:
                path_parts = url_parts.path.strip('/').split('/')
                filename = path_parts[-1] if path_parts else "image"
                
            # Ensure filename has an extension
            if '.' not in filename:
                filename += ".jpg"  # Default extension
                
            # Create a unique path in the cache directory
            cache_path = self.cache_dir / filename
            count = 0
            while cache_path.exists():
                count += 1
                name_parts = filename.split('.')
                if len(name_parts) > 1:
                    ext = name_parts[-1]
                    base = '.'.join(name_parts[:-1])
                    new_filename = f"{base}_{count}.{ext}"
                else:
                    new_filename = f"{filename}_{count}"
                cache_path = self.cache_dir / new_filename
            
            # Download the image
            response = self.http_client.get(url)
            response.raise_for_status()
            
            # Save to disk
            with open(cache_path, 'wb') as f:
                f.write(response.content)
                
            # Cache the path
            self.image_cache[url] = cache_path
            return cache_path
            
        except Exception as e:
            logger.error(f"Failed to fetch image from {url}: {e}")
            return None

    def render_image(self, image_path: Path):
        """Render an image for display in the terminal.
        
        Args:
            image_path: Path to local image file
            
        Returns:
            Either a Rich Pixels object (for rich-pixels rendering) or
            a Path object (for TerminalImage widget)
        """
        if not image_path.exists():
            logger.error(f"Image not found: {image_path}")
            return image_path  # Return path anyway to show error message
        
        try:
            if self.use_native_protocols:
                # For terminal-native protocols, just return the path
                # and let the TerminalImage widget handle rendering
                return image_path
            else:
                # Use rich-pixels for rendering
                img = PILImage.open(image_path)
                # Resize to fit terminal constraints
                img.thumbnail((self.max_width, self.max_height))
                # Create the rich-pixels representation
                return Pixels.from_image(img)
            
        except Exception as e:
            logger.error(f"Failed to render image {image_path}: {e}")
            return image_path  # Return path anyway to show error message

    def process_images(self, images):
        """Process a list of images and return renderable objects.
        
        Args:
            images: List of image info dictionaries with url and alt keys
            
        Returns:
            Dictionary mapping image URLs to renderable objects
        """
        rendered_images = {}
        
        for img_info in images:
            url = img_info["url"]
            
            try:
                # Fetch the image
                image_path = self.fetch_image(url)
                if not image_path:
                    continue
                    
                # For terminal-native protocols, just store the path
                # For rich-pixels, render and store the pixels
                rendered = self.render_image(image_path)
                if rendered:
                    rendered_images[url] = rendered
                    
            except Exception as e:
                logger.error(f"Error processing image {url}: {e}")
                
        return rendered_images

    def clear_cache(self) -> None:
        """Clear the image cache."""
        try:
            # Remove all files in the cache directory
            for file_path in self.cache_dir.glob("*"):
                if file_path.is_file():
                    file_path.unlink()
                    
            # Clear the cache dictionary
            self.image_cache.clear()
            
        except Exception as e:
            logger.error(f"Error clearing image cache: {e}")