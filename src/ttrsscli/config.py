"""Configuration module for ttrsscli."""

import argparse
import concurrent.futures
import json
import logging
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

import toml

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
directory = "/Users/<username>/Documents"
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


def optimize_op_commands(config_dict: dict[str, Any]) -> dict[str, str]:  # noqa: PLR0912, PLR0915
    """Optimally process 1Password commands to minimize CLI calls.

    This function analyzes 1Password commands to see if they reference the same
    item and can be fetched in a single call using 'op item get' with JSON output.

    Args:
        config_dict: Dictionary of config keys to raw values

    Returns:
        Dictionary of config keys to processed values
    """
    # Separate 1Password commands from regular values
    op_commands = {}
    regular_values = {}

    for key, value in config_dict.items():
        if isinstance(value, str) and value.startswith("op "):
            op_commands[key] = value
        else:
            regular_values[key] = value

    # If no 1Password commands, return as-is
    if not op_commands:
        return {k: str(v) for k, v in config_dict.items()}

    # Group commands by 1Password item (if they use 'op item get')
    item_groups = {}
    individual_commands = {}

    for key, op_command in op_commands.items():
        # Check if it's an 'op item get' command that we can optimize
        parts = op_command.split()
        MIN_OP_ITEM_GET_PARTS = 3
        MIN_PARTS_WITH_ID = 4
        if (
            len(parts) >= MIN_OP_ITEM_GET_PARTS
            and parts[1] == "item"
            and parts[2] == "get"
        ):
            # Extract the item identifier (usually the 4th part)
            if len(parts) >= MIN_PARTS_WITH_ID:
                item_id = parts[3]
                if item_id not in item_groups:
                    item_groups[item_id] = {}

                # Extract field name if specified
                field_name = None
                for i, part in enumerate(parts):
                    if part == "--field" and i + 1 < len(parts):
                        field_name = parts[i + 1]
                        break

                item_groups[item_id][key] = {"command": op_command, "field": field_name}
            else:
                individual_commands[key] = op_command
        else:
            individual_commands[key] = op_command

    processed_op_values = {}

    # Process grouped items in parallel (fetch entire items)
    if item_groups:

        def fetch_item(item_id_fields_tuple):
            item_id, fields = item_id_fields_tuple
            result = subprocess.run(
                ["op", "item", "get", item_id, "--format", "json"],
                capture_output=True,
                text=True,
                check=True,
            )
            return item_id, fields, json.loads(result.stdout)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            item_futures = {
                executor.submit(fetch_item, (item_id, fields)): item_id
                for item_id, fields in item_groups.items()
            }

            for future in concurrent.futures.as_completed(item_futures):
                try:
                    item_id, fields, item_data = future.result()

                    # Extract requested fields from the JSON
                    for key, field_info in fields.items():
                        field_name = field_info["field"]
                        if field_name:
                            # Look for the field in the item data
                            field_value = None
                            if "fields" in item_data:
                                for field in item_data["fields"]:
                                    if (
                                        field.get("label") == field_name
                                        or field.get("id") == field_name
                                    ):
                                        field_value = field.get("value", "")
                                        break

                            if field_value is not None:
                                processed_op_values[key] = field_value
                            else:
                                # Fall back to individual command
                                fallback_result = subprocess.run(
                                    field_info["command"].split(),
                                    capture_output=True,
                                    text=True,
                                    check=True,
                                )
                                processed_op_values[key] = (
                                    fallback_result.stdout.strip()
                                )
                        else:
                            # No specific field, use the original command
                            fallback_result = subprocess.run(
                                field_info["command"].split(),
                                capture_output=True,
                                text=True,
                                check=True,
                            )
                            processed_op_values[key] = fallback_result.stdout.strip()

                except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
                    # If optimized approach fails, fall back to individual commands
                    item_id = item_futures[future]
                    fields = item_groups[item_id]
                    for key, field_info in fields.items():
                        try:
                            result = subprocess.run(
                                field_info["command"].split(),
                                capture_output=True,
                                text=True,
                                check=True,
                            )
                            processed_op_values[key] = result.stdout.strip()
                        except subprocess.CalledProcessError as err:
                            logger.error(
                                msg=f"Error executing command '{field_info['command']}': {err}"
                            )
                            print(
                                f"Error executing command '{field_info['command']}': {err}"
                            )
                            sys.exit(1)

    # Process individual commands in parallel using ThreadPoolExecutor
    if individual_commands:

        def run_op_command(key_command_tuple):
            key, op_command = key_command_tuple
            result = subprocess.run(
                op_command.split(), capture_output=True, text=True, check=True
            )
            return key, result.stdout.strip()

        # Run commands in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_key = {
                executor.submit(run_op_command, (key, cmd)): key
                for key, cmd in individual_commands.items()
            }

            for future in concurrent.futures.as_completed(future_to_key):
                try:
                    key, value = future.result()
                    processed_op_values[key] = value
                except subprocess.CalledProcessError as err:
                    logger.error(msg=f"Error executing 1Password command: {err}")
                    print(f"Error executing 1Password command: {err}")
                    sys.exit(1)
                except FileNotFoundError:
                    logger.error(
                        msg="Error: 'op' command not found. Ensure 1Password CLI is installed and accessible."
                    )
                    print(
                        "Error: 'op' command not found. Ensure 1Password CLI is installed and accessible."
                    )
                    sys.exit(1)

    # Combine results
    result = {k: str(v) for k, v in regular_values.items()}
    result.update(processed_op_values)
    return result


class Configuration:
    """A class to handle configuration values."""

    def __init__(self, arguments) -> None:
        """Initialize the configuration.

        Args:
            arguments: Command line arguments
        """
        args = self._parse_arguments(arguments)
        self._setup_logging(args)
        self._handle_special_arguments(args)
        self._load_and_process_configuration(args)

    def _parse_arguments(self, arguments) -> argparse.Namespace:
        """Parse command line arguments.

        Args:
            arguments: Command line arguments

        Returns:
            Parsed arguments namespace
        """
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

        return arg_parser.parse_args(args=arguments)

    def _setup_logging(self, args: argparse.Namespace) -> None:
        """Set up logging configuration.

        Args:
            args: Parsed command line arguments
        """
        if not args.debug and not args.info and not args.error:
            args.ttrsscli_log = "/dev/null"

        # Set up logging with appropriate level
        log_level = (
            logging.ERROR
            if args.error
            else (logging.DEBUG if args.debug else logging.INFO)
        )

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(filename=args.ttrsscli_log),
            ],
        )
        logger: logging.Logger = logging.getLogger(name=__name__)

        # Log initial message based on level
        if args.debug:
            logger.debug(msg="Debug logging enabled")
        elif args.info:
            logger.info(msg="Info logging enabled")
        elif args.error:
            logger.error(msg="Error logging enabled")

    def _handle_special_arguments(self, args: argparse.Namespace) -> None:
        """Handle version and create-config arguments that exit immediately.

        Args:
            args: Parsed command line arguments
        """
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

    def _load_and_process_configuration(self, args: argparse.Namespace) -> None:
        """Load configuration file and process all settings.

        Args:
            args: Parsed command line arguments
        """
        # Load the configuration file
        self.config: dict[str, Any] = self.load_config_file(config_file=args.config)

        try:
            # Optimize TTRSS credentials for faster startup
            ttrss_config_raw = {
                "api_url": self.config["ttrss"].get("api_url", ""),
                "username": self.config["ttrss"].get("username", ""),
                "password": self.config["ttrss"].get("password", ""),
            }
            ttrss_processed = optimize_op_commands(ttrss_config_raw)

            self.api_url: str = ttrss_processed["api_url"]
            self.username: str = ttrss_processed["username"]
            self.password: str = ttrss_processed["password"]

            # Get general settings with defaults
            general_config = self.config.get("general", {})
            general_config_raw = {
                "download_folder": general_config.get(
                    "download_folder", os.path.expanduser(path="~/Downloads")
                )
            }
            general_processed = optimize_op_commands(general_config_raw)

            self.download_folder: Path = Path(general_processed["download_folder"])
            self.auto_mark_read: bool = general_config.get("auto_mark_read", True)
            self.cache_size: int = general_config.get("cache_size", 10000)
            self.default_theme: str = general_config.get("default_theme", "dark")

            # Batch process all other optional settings
            readwise_config = self.config.get("readwise", {})
            obsidian_config = self.config.get("obsidian", {})

            optional_config_raw = {
                "readwise_token": readwise_config.get("token", ""),
                "obsidian_directory": obsidian_config.get("directory", ""),
                "obsidian_vault": obsidian_config.get("vault", ""),
                "obsidian_folder": obsidian_config.get("folder", ""),
                "obsidian_default_tag": obsidian_config.get("default_tag", ""),
                "obsidian_template": obsidian_config.get("template", ""),
            }
            optional_processed = optimize_op_commands(optional_config_raw)

            # Get readwise settings
            self.readwise_token: str = optional_processed["readwise_token"]

            # Get obsidian settings
            self.obsidian_directory: str = optional_processed["obsidian_directory"]
            self.obsidian_vault: str = optional_processed["obsidian_vault"]
            self.obsidian_folder: str = optional_processed["obsidian_folder"]
            self.obsidian_default_tag: str = optional_processed["obsidian_default_tag"]
            self.obsidian_include_tags: bool = obsidian_config.get(
                "include_tags", False
            )
            self.obsidian_include_labels: bool = obsidian_config.get(
                "include_labels", True
            )
            self.obsidian_template: str = optional_processed["obsidian_template"]

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
                print(
                    f"Config file {config_file} not found. Creating with default settings."
                )
                config_path.write_text(data=DEFAULT_CONFIG)
                print(
                    f"Created {config_file} with default settings. Please edit it with your settings."
                )
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
