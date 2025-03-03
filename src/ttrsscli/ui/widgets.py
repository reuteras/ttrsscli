"""Custom widgets for ttrsscli."""

import webbrowser
from typing import Any, Generator

from textual import on
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Markdown, MarkdownViewer, TextArea

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

    @on(message_type=Markdown.LinkClicked)
    def handle_link(self, event: Markdown.LinkClicked) -> None:
        """Open links in the default web browser.

        Args:
            event: Link clicked event
        """
        if event.href:
            event.prevent_default()
            webbrowser.open(url=event.href)