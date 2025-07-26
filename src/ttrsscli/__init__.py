"""ttrsscli - A CLI Tool for Tiny Tiny RSS.

A terminal-based application that provides a text user interface (TUI) for reading
articles from a Tiny Tiny RSS instance.
"""

from .main import main

__all__: list[str] = ["main"]

if __name__ == "__main__":
    main()  # pragma: no cover
