"""Markdown processing utilities for ttrsscli."""

import logging
import re
import textwrap

from bs4 import BeautifulSoup
from markdownify import markdownify as md_converter

logger: logging.Logger = logging.getLogger(name=__name__)

def clean_markdown(markdown_text: str) -> str:
    """Clean up markdown text for better readability.

    Args:
        markdown_text: Raw markdown text

    Returns:
        Cleaned markdown text
    """
    # Replace multiple consecutive blank lines with a single one
    markdown_text = re.sub(pattern=r"\n{3,}", repl="\n\n", string=markdown_text)

    # Wrap very long lines for better readability
    lines: list[str] = markdown_text.split(sep="\n")
    wrapped_lines = []

    for line in lines:
        # Don't wrap lines that look like Markdown formatting (headers, lists, code blocks)
        if (
            line.startswith("#")
            or line.startswith("```")
            or line.startswith("- ")
            or line.startswith("* ")
            or line.startswith("> ")
            or line.startswith("|")
            or line.strip() == ""
        ):
            wrapped_lines.append(line)
        else:
            # Wrap long text lines
            wrapped: str = textwrap.fill(text=line, width=10000)
            wrapped_lines.append(wrapped)

    return "\n  ".join(wrapped_lines)

def html_to_markdown(html_content: str) -> str:
    """Convert HTML to markdown.

    Args:
        html_content: HTML content

    Returns:
        Markdown text
    """
    # Parse HTML
    soup = BeautifulSoup(markup=html_content, features="html.parser")

    # Replace images with placeholders
    for img in soup.find_all(name="img"):
        if img.get("src"): # type: ignore
            # Replace with a placeholder or a note about the image
            img_text: str = f"[Image: {img.get('alt', 'No description')}]" # type: ignore
            img.replace_with(soup.new_string(s=img_text))

    # Convert to markdown
    markdown_text: str = md_converter(
        html=str(object=soup)
    ).replace('xml encoding="UTF-8"', "")

    # Clean the markdown
    return clean_markdown(markdown_text=markdown_text)

def extract_links_from_html(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Extract URLs from article content.

    Args:
        soup: BeautifulSoup object with article HTML

    Returns:
        List of tuples with link title and URL
    """
    urls: list[tuple[str, str]] = []
    if soup is None:
        return urls

    for a in soup.find_all(name="a"):
        try:
            href: str = a.get("href", "") # type: ignore
            if href:
                text: str = a.get_text().strip()
                if not text:  # If link text is empty
                    text = href  # Use the URL as the text
                urls.append((text, href))
        except Exception as e:
            logger.debug(msg=f"Error processing link: {e}")

    return urls
