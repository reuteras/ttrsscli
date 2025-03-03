"""Rich markdown rendering utilities for ttrsscli."""

import logging
import re

from bs4 import BeautifulSoup
from markdownify import markdownify
from rich.console import Console
from rich.markdown import Markdown

from .url import get_clean_url

logger = logging.getLogger(name=__name__)


class RichMarkdownRenderer:
    """A renderer for markdown content using Rich."""

    def __init__(self, clean_urls: bool = True) -> None:
        """Initialize the markdown renderer.

        Args:
            clean_urls: Whether to clean URLs in the markdown
        """
        self.clean_urls = clean_urls
        self.console = Console()

    def render_html_to_markdown(self, html_content: str) -> str:
        """Convert HTML to markdown.

        Args:
            html_content: HTML content

        Returns:
            Markdown text
        """
        # Parse HTML
        soup = BeautifulSoup(markup=html_content, features="html.parser")
        
        # Process and mark images for later handling
        for img in soup.find_all(name="img"):
            if img.get("src"): # type: ignore
                # Mark images with a special tag that will be processed later
                img_alt = img.get("alt", "No description") # type: ignore
                img_src = img.get("src") # type: ignore
                if self.clean_urls:
                    img_src = get_clean_url(url=img_src) # type: ignore
                
                # Create a placeholder that we can find and replace later
                img_placeholder = f"[IMG:{img_src}|{img_alt}]"
                img.replace_with(soup.new_string(s=img_placeholder))
        
        # Clean up any code blocks to ensure proper rendering
        for pre in soup.find_all("pre"):
            # Extract the code language if available
            code_tag = pre.find("code")
            if code_tag and code_tag.get("class"):
                classes = code_tag.get("class")
                language = None
                if classes:
                    for cls in classes:
                        if cls.startswith("language-"):
                            language = cls.replace("language-", "")
                            break
                
                if language:
                    # Mark the code block with language
                    code_content = code_tag.get_text()
                    pre.replace_with(soup.new_string(f"```{language}\n{code_content}\n```"))
        
        # Process links to clean URLs if needed
        if self.clean_urls:
            for a in soup.find_all("a"):
                if a.get("href"):
                    a["href"] = get_clean_url(url=a["href"])
        
        # Convert to markdown
        markdown_text = markdownify(html=str(object=soup))
        
        # Clean up the markdown
        markdown_text = self._clean_markdown(markdown_text=markdown_text)
        
        return markdown_text

    def _clean_markdown(self, markdown_text: str) -> str:
        """Clean up markdown text for better readability.

        Args:
            markdown_text: Raw markdown text

        Returns:
            Cleaned markdown text
        """
        # Replace multiple consecutive blank lines with a single one
        markdown_text = re.sub(pattern=r"\n{3,}", repl="\n\n", string=markdown_text)
        
        # Fix code blocks that might have been malformed
        markdown_text = re.sub(r'```\s+([a-zA-Z0-9]+)\s*\n', r'```\1\n', markdown_text)
        
        # Ensure there are blank lines before and after headings, lists, code blocks
        markdown_text = re.sub(r'([^\n])\n(#{1,6} )', r'\1\n\n\2', markdown_text)
        markdown_text = re.sub(r'(#{1,6} .*)\n([^\n])', r'\1\n\n\2', markdown_text)
        
        # Ensure proper spacing around lists
        markdown_text = re.sub(r'([^\n])\n(- |\* |[0-9]+\. )', r'\1\n\n\2', markdown_text)
        
        # Ensure proper spacing around code blocks
        markdown_text = re.sub(r'([^\n])\n```', r'\1\n\n```', markdown_text)
        markdown_text = re.sub(r'```\n([^\n])', r'```\n\n\1', markdown_text)
        
        return markdown_text

    def extract_images(self, markdown_text: str) -> tuple[str, list[dict[str, str]]]:
        """Extract image placeholders from markdown for separate handling.
        
        Args:
            markdown_text: Markdown text with image placeholders
            
        Returns:
            Tuple containing:
                - Updated markdown with image placeholders removed
                - List of image information dictionaries
        """
        images = []
        
        # Find all image placeholders [IMG:url|alt]
        img_pattern = r'\[IMG:([^|]+)\|([^\]]*)\]'
        for match in re.finditer(img_pattern, markdown_text):
            img_url = match.group(1)
            img_alt = match.group(2)
            
            images.append({
                "url": img_url,
                "alt": img_alt,
                "placeholder": match.group(0)
            })
        
        # Remove image placeholders from markdown text
        # (we'll handle them separately)
        clean_markdown = re.sub(img_pattern, '', markdown_text)
        
        return clean_markdown, images

    def render_markdown(self, markdown_text: str) -> Markdown:
        """Render markdown text to a Rich Markdown object.
        
        Args:
            markdown_text: Markdown text
            
        Returns:
            Rich Markdown object
        """
        # Create a Rich Markdown object
        return Markdown(
            markup=markdown_text,
            hyperlinks=True,
            code_theme="monokai"
        )

    def extract_links(self, markdown_text: str) -> list[tuple[str, str]]:
        """Extract links from markdown text.
        
        Args:
            markdown_text: Markdown text
            
        Returns:
            List of tuples with link title and URL
        """
        links = []
        
        # Extract Markdown-style links [title](url)
        link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        for match in re.finditer(link_pattern, markdown_text):
            title = match.group(1)
            url = match.group(2)
            links.append((title, url))
        
        # Extract HTML-style links that might remain
        html_link_pattern = r'<a\s+href="([^"]+)"[^>]*>([^<]+)</a>'
        for match in re.finditer(html_link_pattern, markdown_text):
            url = match.group(1)
            title = match.group(2)
            links.append((title, url))
        
        return links