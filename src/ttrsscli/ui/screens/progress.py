"""Progress screen for ttrsscli."""

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import ProgressBar, Static


class ProgressScreen(ModalScreen):
    """Screen that shows progress for long operations."""

    def compose(self) -> ComposeResult:
        """Define the content layout of the progress screen."""
        yield Static(content="Working...", id="progress-text")
        yield ProgressBar(total=100, id="progress-bar")