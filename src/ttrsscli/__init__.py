"""ttrsscli - A CLI Tool for Tiny Tiny RSS.

A terminal-based application that provides a text user interface (TUI) for reading
articles from a Tiny Tiny RSS instance.
"""

from .main import main, main_web

__all__: list[str] = ["main", "main_web"]

if __name__ == "__main_web__":
    main_web()  # pragma: no cover

if __name__ == "__main__":
    main()  # pragma: no cover
