# ttrsscli - A CLI Tool for Tiny Tiny RSS

**This has been a sample project for me to use AI to create an app.** The initial version with limited functionality was created with OpenAI but it been rewritten by me even though I have used AI to help me with some parts of the code. Especially parts with textual since it is a new library for me.

`ttrsscli` is a terminal-based application that provides a text user interface (TUI) for reading articles from a [Tiny Tiny RSS](https://tt-rss.org/) instance. Built using [Textual](https://github.com/Textualize/textual), `ttrsscli` allows users to navigate and read their RSS feeds efficiently from the command line.

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
- (Optional) [1Password CLI](https://developer.1password.com/docs/cli) for secure credential and configuration management

### Install

```
uvx tool install ttrsscli
```

Create a _config.toml_ file by running by running `ttrsscli` once.

After that you can just run `ttrsscli`.

## Keyboard Shortcuts

```sh
## Navigation
- **j / k / n**: Navigate articles
- **J / K**: Navigate categories
- **Arrow keys**: Up and down in current pane
- **tab / shift+tab**: Navigate panes

## General keys
- **h / ?**: Show this help
- **q**: Quit
- **G / ,**: Refresh
- **c**: Clear content in article pane
- **d**: Toggle dark and light mode

## Article keys
- **H**: Toggle "header" (info) for article
- **l**: Add article to Readwise
- **L**: Add article to Readwise and open that Readwise page in browser
- **M**: View markdown source for article
- **m**: Maximize content pane (ESC to minimize)
- **r**: Toggle read/unread
- **s**: Star article
- **O**: Export markdown to Obsidian
- **o**: Open article in browser
- **ctrl+l**: Open list with links in article, selected link is sent to Readwise
- **ctrl+L**: Open list with links in article, selected link is sent to Readwise and opened in browser
- **ctrl+o**: Open list with links in article, selected link opens in browser
- **ctrl+s**: Save selected link from article to download folder

## Category and feed keys
- **e**: Toggle expand category
- **g**: Toggle group articles to feed
- **R**: Open recently read articles
- **S**: Show special categories
- **u**: Show all categories (include unread)
```

## License

This project is licensed under the MIT License.

## Contributing

Contributions, issues, and feature requests are welcome! Feel free to open an issue or submit a pull request on [GitHub](https://github.com/reuteras/ttrsscli).

## Author

Developed by [reuteras](https://github.com/reuteras).

## Roadmap

Some thoughts are listed below:

### More functions

> Implement more functions from the [Python API] https://github.com/Vassius/ttrss-python/blob/master/ttrss/client.py). For example add and remove feeds.

I've done a fork of the `ttrss-python` library to be able to add some more features.

- Should the tool use a [timer]( https://textual.textualize.io/api/timer/) to check that updater is running and indicate it at regular intervals?
- Add code for [testing](https://textual.textualize.io/guide/testing/).
- Switch to rich [markdown](https://rich.readthedocs.io/en/stable/markdown.html) to get more features and later images (see below).
- Add support for [images](https://github.com/Textualize/textual/discussions/4345) via [rich-pixels](https://github.com/darrenburns/rich-pixels)
