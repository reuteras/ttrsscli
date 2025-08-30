"""Error handling utilities for ttrsscli."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def log_and_notify(
    app: Any,
    error: Exception,
    title: str,
    message: str | None = None,
    severity: str = "error",
) -> None:
    """Log an error and show a notification to the user.

    Args:
        app: The Textual app instance (should have notify method)
        error: The exception that occurred
        title: Title for the notification
        message: Custom message, if None uses str(error)
        severity: Notification severity level
    """
    error_msg = message or str(error)
    logger.error(f"{title}: {error}")
    app.notify(title=title, message=error_msg, severity=severity)


def log_and_notify_success(
    app: Any, title: str, message: str, timeout: int = 3
) -> None:
    """Log a success message and show a notification.

    Args:
        app: The Textual app instance
        title: Title for the notification
        message: Success message
        timeout: Notification timeout in seconds
    """
    logger.info(f"{title}: {message}")
    app.notify(title=title, message=message, timeout=timeout)
