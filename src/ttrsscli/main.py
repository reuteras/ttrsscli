"""Main entry point for ttrsscli."""

import logging
import sys

from ttrss.exceptions import TTRNotLoggedIn
from urllib3.exceptions import NameResolutionError

from ttrsscli.ui.app import ttrsscli

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(filename="ttrsscli.log"),
    ],
)
logger: logging.Logger = logging.getLogger(name=__name__)

# Create the application instance 
app = ttrsscli()

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
        app.run()
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        print("\nExiting ttrsscli...")
    except TTRNotLoggedIn:
        logger.error(msg="Could not log in to Tiny Tiny RSS. Check your credentials.")
        print("Error: Could not log in to Tiny Tiny RSS. Check your credentials.")
        sys.exit(1)
    except NameResolutionError:
        logger.error(msg="Couldn't look up server for url.")
        print("Error: Couldn't look up server for url.")
        sys.exit(1)
    except Exception as e:
        logger.error(msg=f"Unhandled exception: {e}")
        print(f"Error: {e}")
        print("See ttrsscli.log for details")
        sys.exit(1)


def main_web() -> None:
    """Run the ttrsscli app in web mode."""
    from textual_serve.server import Server

    app = Server(command="ttrsscli")
    app.serve()


if __name__ == "__main__":
    main()