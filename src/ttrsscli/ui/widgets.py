"""Custom widgets for ttrsscli."""

import webbrowser

from textual import on
from textual.widgets import Markdown, MarkdownViewer

# Shared constants
ALLOW_IN_FULL_SCREEN: list[str] = [
    "arrow_up",
    "arrow_down",
    "page_up",
    "page_down",
    "down",
    "up",
    "right",
    "left",
    "enter",
]


class LinkableMarkdownViewer(MarkdownViewer):
    """An extended MarkdownViewer that allows web links to be clicked."""

    def __init__(self, **kwargs) -> None:
        """Initialize the LinkableMarkdownViewer.

        Args:
            **kwargs: Additional arguments
        """
        super().__init__(**kwargs)


    @on(message_type=Markdown.LinkClicked)
    def handle_link(self, event: Markdown.LinkClicked) -> None:
        """Open links in the default web browser.

        Args:
            event: Link clicked event
        """
        if event.href:
            event.prevent_default()
            webbrowser.open(url=event.href)