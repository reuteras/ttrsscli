# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ttrsscli** is a terminal-based RSS reader application that provides a text user interface (TUI) for [Tiny Tiny RSS](https://tt-rss.org/) instances. Built with [Textual](https://github.com/Textualize/textual), it allows users to browse and read RSS feeds efficiently from the command line.

### Key Features

- **Three-pane TUI**: Categories (left), Articles (top-right), Content (bottom-right)
- **Keyboard-driven navigation** with vim-like shortcuts (j/k, J/K)
- **Article management**: Mark read/unread, star articles, open in browser
- **External integrations**: Readwise API, Obsidian URI scheme, 1Password CLI
- **Content processing**: HTML-to-Markdown conversion with link extraction
- **Secure configuration**: TOML-based config with 1Password CLI integration

### Technologies & Dependencies

**Core Framework & UI**
- **Textual**: Modern TUI framework for rich, interactive terminal applications
- **Textual CSS (.tcss)**: Styling system for the terminal interface
- **Python 3.12+**: Modern Python with type hints and async support

**API & HTTP**
- **ttrss-python**: Custom fork for Tiny Tiny RSS API integration
- **httpx**: Modern async HTTP client for API requests
- **requests**: HTTP library for synchronous operations

**Content Processing**
- **BeautifulSoup4**: HTML parsing and manipulation
- **markdownify**: HTML to Markdown conversion
- **cleanurl**: URL cleaning and normalization

**External Integrations**
- **readwise-api**: Integration with Readwise for save-for-later functionality
- **1Password CLI (`op`)**: Secure credential management

**Configuration & Data**
- **TOML**: Configuration file format and parsing
- **Custom caching**: LimitedSizeDict for article metadata

**Development Tools**
- **uv**: Modern Python package manager and build tool
- **ruff**: Fast Python linter and formatter
- **pylint**: Additional code analysis
- **textual-dev**: Development tools for Textual applications

## Development Commands

### Linting and Formatting

```bash
ruff check                    # Lint the code
ruff format                   # Format the code
pylint src/ttrsscli/          # Run pylint analysis
```

### Installation and Building

Use `uv` for package management.

### Running the Application

```bash
ttrsscli                      # Run the CLI app
```

## Code Architecture

### Core Components

**Entry Point & Configuration**

- `main.py`: Entry point with CLI argument parsing and error handling
- `config.py`: Configuration management with TOML parsing and 1Password CLI integration
- Supports `op` command integration for secure credential retrieval

**API Client Layer**

- `client.py`: TTRSSClient wrapper around ttrss-python with session management and caching
- `utils/decorators.py`: Session expiration handling decorator
- Implements automatic re-authentication on session timeout

**UI Architecture (Textual-based)**

- `ui/app.py`: Main ttrsscli app class with 3-pane layout (categories, articles, content)
- `ui/widgets.py`: Custom widgets including LinkableMarkdownViewer
- `ui/screens/`: Modal screens for help, search, feed management, link selection
- `ui/styles.tcss`: Textual CSS styling

**Content Processing**

- `utils/markdown_converter.py`: HTML to Markdown conversion with link extraction
- `utils/markdown.py`: Markdown processing utilities
- `utils/url.py`: URL cleaning and validation
- `cache.py`: LimitedSizeDict for article metadata caching

### Key Design Patterns

**Three-Pane Layout**: Categories (left) → Articles (right top) → Content (right bottom)

- Categories can be expanded to show feeds
- Articles can be grouped by feed or shown as flat list
- Content displays rendered markdown with custom viewer

**State Management**: 

- App maintains current article, category, and UI state
- Uses reactive properties for UI updates
- Caches API responses to reduce server load

**Keyboard-Driven Navigation**:
- Comprehensive key bindings for navigation (j/k, J/K, tab/shift+tab)
- Action methods for all operations (mark read, star, export, etc.)
- Modal screens for complex operations

**External Integrations**:
- Readwise API for save-for-later functionality
- Obsidian URI scheme for note creation
- 1Password CLI for secure credential management
- Clean URL support via cleanurl library

### Error Handling

- Session expiration decorator automatically re-authenticates
- Graceful error handling with user notifications
- Comprehensive logging with configurable levels

### Testing Strategy

No test framework currently configured. When adding tests, consider using pytest with textual's built-in testing utilities for UI components.

