"""HTML to Markdown conversion utilities for ttrsscli."""

import logging
import re

from bs4 import BeautifulSoup
from markdownify import markdownify

from .url import get_clean_url

logger: logging.Logger = logging.getLogger(name=__name__)


def render_html_to_markdown(html_content: str, clean_urls: bool = True) -> str:
    """Convert HTML to markdown.

    Args:
        html_content: HTML content
        clean_urls: Whether to clean URLs in the markdown

    Returns:
        Markdown text
    """
    # Parse HTML
    soup = BeautifulSoup(markup=html_content, features="html.parser")
    
    # Replace images with text descriptions
    for img in soup.find_all(name="img"):
        if img.get("src"):  # type: ignore
            # Create a text placeholder for images
            img_alt: str = img.get("alt", "No description")  # type: ignore
            img_placeholder: str = f"[Image: {img_alt}]"
            img.replace_with(soup.new_string(s=img_placeholder))
    
    # Clean up any code blocks to ensure proper rendering
    for pre in soup.find_all(name="pre"):
        # Extract the code language if available
        code_tag = pre.find("code")  # type: ignore
        if code_tag and code_tag.get("class"):  # type: ignore
            classes: str = code_tag.get("class")  # type: ignore
            language = ""
            if classes:
                for cls in classes:
                    if cls.startswith("language-"):
                        language: str = cls.replace("language-", "")
                        break
            
            if language:
                # Mark the code block with language
                code_content: str = code_tag.get_text()  # type: ignore
                pre.replace_with(soup.new_string(f"```{language}\n{code_content}\n```"))
    
    # Process links to clean URLs if needed
    if clean_urls:
        for a in soup.find_all(name="a"):
            if a.get("href"):  # type: ignore
                a["href"] = get_clean_url(url=a["href"])  # type: ignore
    
    # Convert to markdown
    markdown_text: str = markdownify(html=str(object=soup))
    
    # Clean up the markdown
    markdown_text = _clean_markdown(markdown_text=markdown_text)
    
    return markdown_text


def _clean_markdown(markdown_text: str) -> str:
    """Clean up markdown text for better readability.

    Args:
        markdown_text: Raw markdown text

    Returns:
        Cleaned markdown text
    """
    # Replace multiple consecutive blank lines with a single one
    markdown_text = re.sub(pattern=r"\n{3,}", repl="\n\n", string=markdown_text)
    
    # Fix code blocks that might have been malformed
    markdown_text = re.sub(pattern=r'```\s+([a-zA-Z0-9]+)\s*\n', repl=r'```\1\n', string=markdown_text)
    
    # Ensure there are blank lines before and after headings, lists, code blocks
    markdown_text = re.sub(pattern=r'([^\n])\n(#{1,6} )', repl=r'\1\n\n\2', string=markdown_text)
    markdown_text = re.sub(pattern=r'(#{1,6} .*)\n([^\n])', repl=r'\1\n\n\2', string=markdown_text)
    
    # Ensure proper spacing around lists
    markdown_text = re.sub(pattern=r'([^\n])\n(- |\* |[0-9]+\. )', repl=r'\1\n\n\2', string=markdown_text)
    
    # Ensure proper spacing around code blocks
    markdown_text = re.sub(pattern=r'([^\n])\n```', repl=r'\1\n\n```', string=markdown_text)
    markdown_text = re.sub(pattern=r'```\n([^\n])', repl=r'```\n\n\1', string=markdown_text)
    
    return markdown_text


def extract_links(markdown_text: str) -> list[tuple[str, str]]:
    """Extract links from markdown text.
    
    Args:
        markdown_text: Markdown text
        
    Returns:
        List of tuples with link title and URL
    """
    links = []
    
    # Extract Markdown-style links [title](url)
    link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
    for match in re.finditer(pattern=link_pattern, string=markdown_text):
        title: str = match.group(1)
        url: str = match.group(2)
        links.append((title, url))
    
    # Extract HTML-style links that might remain
    html_link_pattern = r'<a\s+href="([^"]+)"[^>]*>([^<]+)</a>'
    for match in re.finditer(pattern=html_link_pattern, string=markdown_text):
        url = match.group(1)
        title = match.group(2)
        links.append((title, url))
    
    return links