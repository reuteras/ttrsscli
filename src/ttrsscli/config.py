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

logger = logging.getLogger(name=__name__)

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

    def __init__(self, arguments) -> None:
        """Initialize the configuration.

        Args:
            arguments: Command line arguments
        """
        # Use argparse to add arguments
        arg_parser = argparse.ArgumentParser(
            description="A Textual app to access and read articles from Tiny Tiny RSS."
        )
        arg_parser.add_argument(
            "--config",
            dest="config",
            help="Path to the config file",
            default="config.toml",
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
        args: argparse.Namespace = arg_parser.parse_args(args=arguments)

        if args.debug:
            logger.setLevel(level=logging.DEBUG)
            logger.debug(msg="Debug mode enabled")

        if args.version:
            try:
                version: str = metadata.version(distribution_name="ttrsscli")
                print(f"ttrsscli version: {version}")
                sys.exit(0)
            except Exception as e:
                print(f"Error getting version: {e}")
                sys.exit(1)

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
        default_config_path = Path("config.toml-default")

        try:
            if not config_path.exists():
                # If config file doesn't exist, try to use default config
                if default_config_path.exists():
                    print(
                        f"Config file {config_file} not found. Creating from default."
                    )
                    config_path.write_text(data=default_config_path.read_text())
                    print(
                        f"Created {config_file} from default. Please edit it with your settings."
                    )
                else:
                    print(f"Neither {config_file} nor {default_config_path} found.")
                    sys.exit(1)

            return toml.loads(s=config_path.read_text())
        except (FileNotFoundError, toml.TomlDecodeError) as err:
            logger.error(msg=f"Error reading configuration file: {err}")
            print(f"Error reading configuration file: {err}")
            sys.exit(1)