"""Configuration module for ttrsscli."""

import argparse
import logging
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

import toml
from urllib3.exceptions import NameResolutionError

logger: logging.Logger = logging.getLogger(name=__name__)

# Default configuration content
DEFAULT_CONFIG = """[general]
# Path to download folder (required for saving files)
download_folder = "/Users/<username>/Downloads"
# Whether to automatically mark articles as read when opened
auto_mark_read = true
# Size of the cache for storing article metadata
cache_size = 10000
# Default theme (dark or light)
default_theme = "dark"

[ttrss]
# Tiny Tiny RSS API endpoint - can use op command for 1Password integration
api_url = "https://your-ttrss-instance.com/api/"
username = "your_username"
password = "your_password"  # Or use 1Password CLI integration

[readwise]
# Readwise API token - can use op command for 1Password integration
token = "your_readwise_token"  # Or use 1Password CLI integration

[obsidian]
# Obsidian integration settings
vault = "YourVaultName"
folder = "News"
default_tag = "type/news"
include_tags = true
include_labels = true
template = \"\"\"
---
id: <ID>
created: <% tp.date.now() %>
url: <URL>
aliases:
  - <TITLE>
tags:
  - created/y<% tp.date.now("YYYY") %>
  - <TAGS>
---

<CONTENT>

Last changed: `$= dv.current().file.mtime`
\"\"\"
"""

def get_conf_value(op_command: str) -> str:
    """Get the configuration value from 1Password if config starts with 'op '.

    Args:
        op_command: Configuration value or 1Password command

    Returns:
        The configuration value or the output of the 1Password command

    Raises:
        SystemExit: If the 1Password command fails
    """
    if op_command.startswith("op "):
        try:
            result: subprocess.CompletedProcess[str] = subprocess.run(
                args=op_command.split(), capture_output=True, text=True, check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as err:
            logger.error(msg=f"Error executing command '{op_command}': {err}")
            print(f"Error executing command '{op_command}': {err}")
            sys.exit(1)
        except FileNotFoundError:
            logger.error(
                msg="Error: 'op' command not found. Ensure 1Password CLI is installed and accessible."
            )
            print(
                "Error: 'op' command not found. Ensure 1Password CLI is installed and accessible."
            )
            sys.exit(1)
        except NameResolutionError:
            logger.error(msg="Error: Couldn't look up server for url.")
            print("Error: Couldn't look up server for url.")
            sys.exit(1)
    else:
        return op_command


class Configuration:
    """A class to handle configuration values."""

    def __init__(self, arguments) -> None:  # noqa: PLR0915
        """Initialize the configuration.

        Args:
            arguments: Command line arguments
        """
        # Use argparse to add arguments
        arg_parser = argparse.ArgumentParser(
            description="A Textual app to access and read articles from Tiny Tiny RSS."
        )
        config_file_location: Path = Path.home() / ".ttrsscli.toml"
        arg_parser.add_argument(
            "--config",
            dest="config",
            help="Path to the config file",
            default=config_file_location,
        )
        arg_parser.add_argument(
            "--create-config",
            dest="create_config",
            help="Create a default configuration file at the specified path",
            metavar="PATH",
        )
        arg_parser.add_argument(
            "--version",
            action="store_true",
            dest="version",
            help="Show version and exit",
            default=False,
        )
        arg_parser.add_argument(
            "--debug",
            action="store_true",
            dest="debug",
            help="Enable debug logging",
            default=False,
        )
        arg_parser.add_argument(
            "--info",
            action="store_true",
            dest="info",
            help="Enable info logging",
            default=False,
        )
        arg_parser.add_argument(
            "--error",
            dest="error",
            help="Enable error logging",
            default=False,
        )
        arg_parser.add_argument(
            "--log-file",
            dest="ttrsscli_log",
            help="Path to the log file",
            default="ttrsscli.log",
        )
        args: argparse.Namespace = arg_parser.parse_args(args=arguments)

        if not args.debug and not args.info and not args.error:
            args.ttrsscli_log = "/dev/null"

        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
            logging.FileHandler(filename=args.ttrsscli_log),
        ],
        )
        logger: logging.Logger = logging.getLogger(name=__name__)

        if args.debug:
            logger.setLevel(level=logging.DEBUG)
            logger.debug(msg="Debug log enabled")

        if args.info:
            logger.setLevel(level=logging.INFO)
            logger.info(msg="Info log enabled")

        if args.error:
            logger.setLevel(level=logging.ERROR)
            logger.info(msg="Error log enabled")

        # Handle version argument
        if args.version:
            try:
                version: str = metadata.version(distribution_name="ttrsscli")
                print(f"ttrsscli version: {version}")
                sys.exit(0)
            except Exception as e:
                print(f"Error getting version: {e}")
                sys.exit(1)

        # Handle create-config argument
        if args.create_config:
            self.create_default_config(config_path=args.create_config)
            print(f"Created default configuration at: {args.create_config}")
            print("Please edit this file with your settings before running ttrsscli.")
            sys.exit(0)

        # Load the configuration file
        self.config: dict[str, Any] = self.load_config_file(config_file=args.config)

        try:
            self.api_url: str = get_conf_value(
                op_command=self.config["ttrss"].get("api_url", "")
            )
            self.username: str = get_conf_value(
                op_command=self.config["ttrss"].get("username", "")
            )
            self.password: str = get_conf_value(
                op_command=self.config["ttrss"].get("password", "")
            )

            # Get general settings with defaults
            general_config = self.config.get("general", {})
            self.download_folder: Path = Path(
                get_conf_value(
                    op_command=general_config.get(
                        "download_folder", os.path.expanduser(path="~/Downloads")
                    )
                )
            )
            self.auto_mark_read: bool = general_config.get("auto_mark_read", True)
            self.cache_size: int = general_config.get("cache_size", 10000)
            self.default_theme: str = general_config.get("default_theme", "dark")

            # Get readwise settings
            readwise_config = self.config.get("readwise", {})
            self.readwise_token: str = get_conf_value(
                op_command=readwise_config.get("token", "")
            )

            # Get obsidian settings
            obsidian_config = self.config.get("obsidian", {})
            self.obsidian_vault: str = get_conf_value(
                op_command=obsidian_config.get("vault", "")
            )
            self.obsidian_folder: str = get_conf_value(
                op_command=obsidian_config.get("folder", "")
            )
            self.obsidian_default_tag: str = get_conf_value(
                op_command=obsidian_config.get("default_tag", "")
            )
            self.obsidian_include_tags: bool = obsidian_config.get(
                "include_tags", False
            )
            self.obsidian_include_labels: bool = obsidian_config.get(
                "include_labels", True
            )
            self.obsidian_template: str = get_conf_value(
                op_command=obsidian_config.get("template", "")
            )

            # Make sure download folder exists
            self.download_folder.mkdir(parents=True, exist_ok=True)

            self.version: str = metadata.version(distribution_name="ttrsscli")
        except KeyError as err:
            logger.error(msg=f"Error reading configuration: {err}")
            print(f"Error reading configuration: {err}")
            sys.exit(1)

    def load_config_file(self, config_file: str) -> dict[str, Any]:
        """Load the configuration from the TOML file.

        Args:
            config_file: Path to the config file

        Returns:
            Configuration dictionary

        Raises:
            SystemExit: If the config file cannot be read
        """
        config_path = Path(config_file)

        try:
            if not config_path.exists():
                # If config file doesn't exist, create it from the default config
                print(f"Config file {config_file} not found. Creating with default settings.")
                config_path.write_text(data=DEFAULT_CONFIG)
                print(f"Created {config_file} with default settings. Please edit it with your settings.")
                sys.exit(1)

            return toml.loads(s=config_path.read_text())
        except (FileNotFoundError, toml.TomlDecodeError) as err:
            logger.error(msg=f"Error reading configuration file: {err}")
            print(f"Error reading configuration file: {err}")
            sys.exit(1)

    def create_default_config(self, config_path: str) -> None:
        """Create a default configuration file at the specified path.

        Args:
            config_path: Path where the configuration file should be created

        Raises:
            SystemExit: If the file cannot be written
        """
        path = Path(config_path)

        # Create parent directories if they don't exist
        if not path.parent.exists():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(msg=f"Error creating directory for config file: {e}")
                print(f"Error creating directory for config file: {e}")
                sys.exit(1)

        # Write the default configuration
        try:
            path.write_text(data=DEFAULT_CONFIG)
        except Exception as e:
            logger.error(msg=f"Error writing configuration file: {e}")
            print(f"Error writing configuration file: {e}")
            sys.exit(1)
