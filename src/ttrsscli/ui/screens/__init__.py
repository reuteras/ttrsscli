"""Screen modules for ttrsscli."""

from .confirm_screens import ConfirmMarkAllReadScreen, ConfirmScreen
from .feed_screens import AddFeedScreen, EditFeedScreen
from .fullscreen import FullScreenMarkdown, FullScreenTextArea
from .help import HelpScreen
from .link_screens import LinkSelectionScreen
from .progress import ProgressScreen
from .search import SearchScreen

__all__: list[str] = [
    "AddFeedScreen",
    "ConfirmMarkAllReadScreen",
    "ConfirmScreen",
    "EditFeedScreen",
    "FullScreenMarkdown",
    "FullScreenTextArea",
    "HelpScreen",
    "LinkSelectionScreen",
    "ProgressScreen",
    "SearchScreen",
]