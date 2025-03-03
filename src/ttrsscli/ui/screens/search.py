"""Search screen for ttrsscli."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class SearchScreen(ModalScreen):
    """Modal screen for searching articles."""

    BINDINGS = [  # noqa: RUF012
        ("escape", "close_screen", "Close"),
        ("enter", "search", "Search"),
    ]

    def __init__(self) -> None:
        """Initialize the search screen."""
        super().__init__()
        self.search_term: str = ""

    def compose(self) -> ComposeResult:
        """Define the content layout of the search screen."""
        with Container(id="search-container"):
            yield Label(renderable="Search Articles", id="search-title")
            yield Input(placeholder="Enter search term...", id="search-input")
            with Horizontal(id="search-buttons"):
                yield Button(label="Search", id="search-button")
                yield Button(label="Cancel", id="cancel-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "search-button":
            self.action_search()
        elif event.button.id == "cancel-button":
            self.action_close_screen()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update search term when input changes."""
        self.search_term = event.value

    def action_search(self) -> None:
        """Search for articles with the current search term."""
        if self.search_term:
            self.dismiss(result=self.search_term)
        else:
            self.notify(message="Please enter a search term", title="Search")

    def action_close_screen(self) -> None:
        """Close the search screen."""
        self.dismiss(None)