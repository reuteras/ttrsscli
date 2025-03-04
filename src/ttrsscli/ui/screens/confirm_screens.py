"""Confirmation dialog screens for ttrsscli."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmScreen(ModalScreen):
    """Modal screen for confirming actions like deletion."""

    BINDINGS = [  # noqa: RUF012
        ("escape", "cancel", "Cancel"),
        ("enter", "confirm", "Confirm"),
    ]

    def __init__(
        self, title="Confirm", message="Are you sure?", on_confirm=None
    ) -> None:
        """Initialize the confirmation screen.

        Args:
            title: Title of the confirmation dialog
            message: Message to display
            on_confirm: Callback function to run on confirmation
        """
        super().__init__()
        self.dialog_title: str = title
        self.message: str = message
        self.on_confirm = on_confirm

    def compose(self) -> ComposeResult:
        """Define the content layout of the confirmation screen."""
        with Container(id="confirm-container"):
            yield Label(renderable=self.dialog_title, id="confirm-title")
            yield Label(renderable=self.message, id="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button(label="Confirm", id="confirm-button", variant="error")
                yield Button(label="Cancel", id="cancel-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "confirm-button":
            self.action_confirm()
        elif event.button.id == "cancel-button":
            self.action_cancel()

    def action_confirm(self) -> None:
        """Confirm the action and call the callback."""
        # Pop this screen first
        self.app.pop_screen()

        # Call the callback if provided
        if self.on_confirm:
            self.on_confirm()

    def action_cancel(self) -> None:
        """Cancel the action."""
        self.app.pop_screen()


class ConfirmMarkAllReadScreen(ModalScreen):
    """Modal screen for confirming mark all as read action."""

    BINDINGS = [  # noqa: RUF012
        ("escape", "cancel", "Cancel"),
        ("enter", "confirm", "Confirm"),
    ]

    def __init__(
        self, feed_id, is_cat=False, feed_title="this feed"
    ) -> None:
        """Initialize the confirmation screen.

        Args:
            feed_id: ID of the feed to mark as read
            is_cat: Whether the feed is a category
            feed_title: Title of the feed for display
        """
        super().__init__()
        self.feed_id = feed_id
        self.is_cat: bool = is_cat
        self.feed_title: str = feed_title

    def compose(self) -> ComposeResult:
        """Define the content layout of the confirmation screen."""
        with Container(id="confirm-small-container"):
            yield Label(renderable="Mark All As Read", id="confirm-title")
            yield Label(
                renderable=f"Mark all articles in '{self.feed_title}' as read?",
                id="confirm-message"
            )
            with Horizontal(id="confirm-buttons"):
                yield Button(label="Yes", id="confirm-button", variant="error")
                yield Button(label="No", id="cancel-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "confirm-button":
            self.action_confirm()
        elif event.button.id == "cancel-button":
            self.action_cancel()

    def action_confirm(self) -> None:
        """Confirm the action and mark all articles as read."""
        self.dismiss(result={"confirm": True, "feed_id": self.feed_id, "is_cat": self.is_cat})

    def action_cancel(self) -> None:
        """Cancel the action."""
        self.dismiss(result={"confirm": False})
