# ttcli - A CLI Tool for Tiny Tiny RSS

**This has been a sample project for me to use AI to create an app.**

`ttcli` is a terminal-based application that provides a text user interface (TUI) for reading articles from a [Tiny Tiny RSS](https://tt-rss.org/) instance. Built using [Textual](https://github.com/Textualize/textual), `ttcli` allows users to navigate and read their RSS feeds efficiently from the command line.

## Features

- **Browse Categories & Feeds**: View unread or all categories and feeds.
- **Read Articles**: Select articles to read in a formatted text view.
- **Keyboard Navigation**: Use intuitive keyboard shortcuts for fast browsing.
- **Mark Articles Read/Unread**: Easily toggle read status of articles.
- **Star Articles**: Mark important articles for later reference.
- **Open in Browser**: Open the original article in your default web browser.
- **1Password Integration**: Fetch credentials securely using 1Password CLI.
- **Configuration via TOML**: Use a simple `config.toml` file to manage API credentials.

## Installation

### Prerequisites
- Python 3.11+
- Tiny Tiny RSS instance
- `uv` for dependency installation
- (Optional) [1Password CLI](https://developer.1password.com/docs/cli) for secure credential management

### Install Dependencies

Checkout and install requirements.

```sh
git clone https://github.com/reuteras/ttcli.git && cd ttcli
uv sync
source .venv/bin/activate
```

## Configuration

Create a `config.toml` file in the same directory with the following structure:
```toml
[ttrss]
api_url = "https://your-ttrss-instance.com/api/"
username = "your_username"
password = "your_password"  # Or "op read op://Private/ttrss/password --no-newline"" if using 1Password CLI
```

## Running

Start `ttcli`.

```sh
textual run ttcli.py
```

## Keyboard Shortcuts

```sh
| Key                   | Action                         |
|-----------------------|--------------------------------|
| `?` / `h` / `H`       | Show help screen               |
| `c`                   | Clear content pane             |
| `e`                   | Expand/collapse categories     |
| `g`                   | Toggle group feeds             |
| `j` / `k`             | Navigate articles              |
| `J` / `K`             | Navigate categories            |
| `m`                   | Maximize pane                  |
| `M`                   | Minimize pane                  |
| `o`                   | Open article in browser        |
| `r`                   | Mark read/unread               |
| `s`                   | Star/unstar article            |
| `u`                   | Toggle unread categories only  |
| `,`                   | Refresh feeds                  |
| `tab` / `shift+tab`   | Switch between panes           |
| `q`                   | Quit application               |
```

## License

This project is licensed under the MIT License.

## Contributing

Contributions, issues, and feature requests are welcome! Feel free to open an issue or submit a pull request on [GitHub](https://github.com/reuteras/ttcli).

## Author

Developed by [reuteras](https://github.com/reuteras).

## Roadmap

Some thoughts are listed below:

- Implement more functions from the [Python API] https://github.com/Vassius/ttrss-python/blob/master/ttrss/client.py). For example add and remove feeds.
- Should a use [timer]( https://textual.textualize.io/api/timer/) to check that updater is running and indicate it?
- Add code for [testing](https://textual.textualize.io/guide/testing/)?
- Switch to rich [markdown](https://rich.readthedocs.io/en/stable/markdown.html)
- Add support for [images](https://github.com/Textualize/textual/discussions/4345) via [rich-pixels](https://github.com/darrenburns/rich-pixels)
