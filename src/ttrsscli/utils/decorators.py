"""Decorator utilities for ttrsscli."""

import functools
import logging
from collections.abc import Callable
from time import sleep
from typing import Any

logger: logging.Logger = logging.getLogger(name=__name__)

def handle_session_expiration(api_method: Callable) -> Callable:
    """Decorator that retries a function call after re-authenticating if session expires.

    Args:
        api_method: The API method to wrap

    Returns:
        A wrapped function that handles session expiration
    """

    @functools.wraps(wrapped=api_method)
    def wrapper(self, *args, **kwargs) -> Any:
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                return api_method(self, *args, **kwargs)
            except ConnectionResetError as err:
                logger.warning(
                    msg=f"Connection reset: {err}. Retrying ({retry_count + 1}/{max_retries})..."
                )
                retry_count += 1
                sleep(1)

                # Re-login
                if not self.login():
                    logger.error(msg="Re-authentication failed after connection reset")
                    raise RuntimeError("Re-authentication failed") from err
            except Exception as err:
                if "NOT_LOGGED_IN" in str(object=err):
                    logger.warning(
                        msg=f"Session expired: {err}. Retrying ({retry_count + 1}/{max_retries})..."
                    )
                    retry_count += 1

                    # Re-login
                    if not self.login():
                        logger.error(
                            msg="Re-authentication failed after session expiration"
                        )
                        raise RuntimeError("Re-authentication failed") from err
                else:
                    # If it's not a session issue, just raise the exception
                    raise

        # If we've exhausted our retries
        logger.error(msg=f"Failed after {max_retries} retries")
        raise RuntimeError(f"Failed after {max_retries} retries")

    return wrapper