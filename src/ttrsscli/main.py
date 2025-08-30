"""Main entry point for ttrsscli."""

import sys

from ttrss.exceptions import TTRNotLoggedIn
from urllib3.exceptions import NameResolutionError

from ttrsscli.ui.app import ttrsscli


def main() -> None:
    """Run the ttrsscli app.

    Usage:
        ttrsscli
        ttrsscli --config path/to/config.toml
        ttrsscli --create-config path/to/config.toml
        ttrsscli --version
        ttrsscli --help
    """
    try:
        # Create the application instance only when running
        app = ttrsscli()
        app.run()
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        print("\nExiting ttrsscli...")
    except TTRNotLoggedIn:
        print("Error: Could not log in to Tiny Tiny RSS. Check your credentials.")
        sys.exit(1)
    except NameResolutionError:
        print("Error: Couldn't look up server for url.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        print("See ttrsscli.log for details")
        sys.exit(1)


if __name__ == "__main__":
    main()
