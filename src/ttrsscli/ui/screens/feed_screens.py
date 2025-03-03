"""Feed management screens for ttrsscli."""

import logging
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    Static,
)

from ...ui.screens import ConfirmScreen

logger: logging.Logger = logging.getLogger(name=__name__)


class AddFeedScreen(ModalScreen):
    """Modal screen for adding a new feed."""

    BINDINGS = [  # noqa: RUF012
        ("escape", "close_screen", "Close"),
        ("enter", "add_feed", "Add Feed"),
    ]

    def __init__(self, client, category_id=0) -> None:
        """Initialize the add feed screen.

        Args:
            client: TTRSS client
            category_id: Optional category ID to add the feed to
        """
        super().__init__()
        self.client = client
        self.category_id: int = category_id
        self.feed_url: str  = ""
        self.feed_name:str = ""
        self.login_user:str = ""
        self.login_pass:str = ""
        self.categories: list[tuple[str, str]] = [("", "")]
        self.selected_category: int = category_id
        self._loading = False

    def compose(self) -> ComposeResult:
        """Define the content layout of the add feed screen."""
        with Container(id="feed-container"):
            yield Label(renderable="Add New Feed", id="feed-title")
            yield Input(placeholder="Feed URL (required)", id="feed-url-input")
            yield Input(placeholder="Feed Title (optional)", id="feed-title-input")
            yield Input(
                placeholder="Login username (if required)", id="login-user-input"
            )
            yield Input(
                password=True,
                placeholder="Login password (if required)",
                id="login-pass-input",
            )

            # Category selection dropdown
            yield Label(renderable="Category:")
            yield ListView(id="category-list")

            # Progress indicator (hidden initially via CSS)
            with Vertical(id="progress-container"):
                yield ProgressBar(total=100, id="add-progress-bar")

            with Horizontal(id="feed-buttons"):
                yield Button(label="Add Feed", id="add-button")
                yield Button(label="Cancel", id="cancel-button")

    def on_mount(self) -> None:
        """Set initial visibility and fetch categories."""
        # Hide progress bar initially
        progress_container: Vertical = self.query_one(selector="#progress-container", expect_type=Vertical)
        progress_container.styles.display = "none"

        # Fetch categories
        self._fetch_categories()

    def _fetch_categories(self) -> None:
        """Fetch categories for the dropdown."""
        try:
            # Fetch categories for the dropdown
            categories = self.client.get_categories()
            category_list: ListView = self.query_one(selector="#category-list", expect_type=ListView)

            for category in sorted(categories, key=lambda x: x.title):
                if category.title != "Special":  # Skip special category
                    item = ListItem(Label(renderable=category.title), id=f"cat_{category.id}")
                    category_list.append(item=item)
                    self.categories.append((category.id, category.title))

            # Select the provided category if any
            if self.category_id is not None:
                for i, (cat_id, _) in enumerate(iterable=self.categories):
                    if cat_id == self.category_id:
                        category_list.index = i
                        break
        except Exception as e:
            self.notify(
                title="Error",
                message=f"Failed to load categories: {e}",
                severity="error",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "add-button":
            self.action_add_feed()
        elif event.button.id == "cancel-button":
            self.action_close_screen()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update variables when input changes."""
        if event.input.id == "feed-url-input":
            self.feed_url = event.value
        elif event.input.id == "feed-title-input":
            self.feed_name = event.value
        elif event.input.id == "login-user-input":
            self.login_user = event.value
        elif event.input.id == "login-pass-input":
            self.login_pass = event.value

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle category selection."""
        if event.list_view.id == "category-list" and event.list_view.index is not None:
            try:
                self.selected_category = int(self.categories[event.list_view.index][0])
            except IndexError:
                # Handle case when the index is out of range
                pass

    def action_add_feed(self) -> None:
        """Add a new feed with the provided details."""
        if not self.feed_url:
            self.notify(
                message="Please enter a feed URL",
                title="Required Field",
                severity="warning",
            )
            return

        try:
            # Show progress indicator
            progress_container: Vertical = self.query_one(selector="#progress-container", expect_type=Vertical)
            progress_container.styles.display = "block"
            self._loading = True

            # Prepare authentication if provided
            auth_login: str | None = self.login_user if self.login_user else None
            auth_pass: str | None = self.login_pass if self.login_pass else None

            # Add the feed
            result = self.client.subscribe_to_feed(
                feed_url=self.feed_url,
                category_id=self.selected_category,
                feed_title=self.feed_name if self.feed_name else None,
                login=auth_login,
                password=auth_pass,
            )

            # Hide progress indicator
            progress_container.styles.display = "none"
            self._loading = False

            if result and hasattr(result, "status") and result.status:
                self.notify(message="Feed added successfully", title="Success")
                self.dismiss(result=True)
            else:
                error_msg = (
                    getattr(result, "message", "Unknown error")
                    if result
                    else "Unknown error"
                )
                self.notify(
                    message=f"Failed to add feed: {error_msg}",
                    title="Error",
                    severity="error",
                )
        except Exception as e:
            # Hide progress indicator if there's an error
            if self._loading:
                progress_container = self.query_one(selector="#progress-container", expect_type=Vertical)
                progress_container.styles.display = "none"
                self._loading = False

            logger.error(msg=f"Error adding feed: {e}")
            self.notify(
                message=f"Error adding feed: {e}", title="Error", severity="error"
            )

    def action_close_screen(self) -> None:
        """Close the screen."""
        self.dismiss(result=False)


class EditFeedScreen(ModalScreen):
    """Modal screen for editing feed properties."""

    BINDINGS = [  # noqa: RUF012
        ("escape", "close_screen", "Close"),
        ("enter", "save_feed", "Save"),
        ("delete", "delete_feed", "Delete Feed"),
    ]

    def __init__(self, client, feed_id, title="", url="") -> None:
        """Initialize the edit feed screen.

        Args:
            client: TTRSS client
            feed_id: Feed ID to edit
            title: Current feed title
            url: Current feed URL
        """
        super().__init__()
        self.client = client
        self.feed_id = feed_id
        self.current_title: str = title
        self.current_url: str = url
        self.feed_title: str = title
        self.categories: list[Any] = []
        self.selected_category = None
        self.current_category_id = None
        self.feed_details = None
        self._loading = False

    def compose(self) -> ComposeResult:
        """Define the content layout of the edit feed screen."""
        with Container(id="feed-container"):
            yield Label(renderable="Edit Feed", id="feed-title")
            yield Input(
                placeholder="Feed Title",
                id="feed-title-input",
                value=self.current_title,
            )

            # Feed URL (disabled, for display only)
            yield Label(renderable="Feed URL:")
            yield Input(
                placeholder="Feed URL",
                id="feed-url-input",
                value=self.current_url,
                disabled=True,
            )

            # Category selection dropdown
            yield Label(renderable="Category:")
            yield ListView(id="category-list")

            # Feed settings
            yield Label(renderable="Settings:")

            with Vertical(id="settings-container"):
                yield Static(content="Loading feed settings...")

            # Progress indicator (hidden using display property)
            with Vertical(id="progress-container"):
                yield ProgressBar(total=100, id="edit-progress-bar")

            with Horizontal(id="feed-buttons"):
                yield Button(label="Save Changes", id="save-button", variant="primary")
                yield Button(label="Cancel", id="cancel-button")
                yield Button(label="Delete Feed", id="delete-button", variant="error")

    def on_mount(self) -> None:
        """Set initial visibility of progress bar."""
        # Hide progress bar initially
        progress_container: Vertical = self.query_one(selector="#progress-container", expect_type=Vertical)
        progress_container.styles.display = "none"

    async def on_show(self) -> None:  # noqa: PLR0912, PLR0915
        """Fetch categories and feed details when screen is shown."""
        try:
            # Show progress indicator
            self._loading = True
            progress_container: Vertical = self.query_one(selector="#progress-container", expect_type=Vertical)
            progress_container.styles.display = "block"

            # Fetch categories for the dropdown
            categories = self.client.get_categories()
            category_list: ListView = self.query_one(selector="#category-list", expect_type=ListView)

            for category in sorted(categories, key=lambda x: x.title):
                if category.title != "Special":  # Skip special category
                    item = ListItem(Label(renderable=category.title), id=f"cat_{category.id}")
                    category_list.append(item=item)
                    self.categories.append((category.id, category.title)) # type: ignore

            # Fetch feed details using get_feed_properties with additional error handling
            try:
                self.feed_details = self.client.get_feed_properties(feed_id=self.feed_id)

                # Update feed URL if available in feed_details
                if self.feed_details:
                    # Update the URL field if feed_url is available
                    if hasattr(self.feed_details, "feed_url") and self.feed_details.feed_url:
                        self.current_url = self.feed_details.feed_url
                        url_input: Input = self.query_one(selector="#feed-url-input", expect_type=Input)
                        url_input.value = self.current_url
                    elif self.current_url:  # Use the URL provided during initialization if available
                        url_input = self.query_one(selector="#feed-url-input", expect_type=Input)
                        url_input.value = self.current_url
                    else:
                        # Notify that URL couldn't be retrieved
                        self.notify(
                            title="Warning",
                            message="Could not retrieve feed URL. This field will be display-only.",
                            severity="warning",
                            timeout=5)

                if not self.feed_details:
                    # If get_feed_properties returns None, try to get feed info from all feeds
                    logger.info(msg=f"Trying to find feed {self.feed_id} in all feeds")
                    all_feeds = []
                    for category in categories:
                        try:
                            feeds = self.client.get_feeds(cat_id=category.id, unread_only=False)
                            all_feeds.extend(feeds)
                        except Exception as feed_err:
                            logger.warning(msg=f"Error getting feeds for category {category.id}: {feed_err}")

                    # Find the feed in all_feeds
                    for feed in all_feeds:
                        if int(feed.id) == int(self.feed_id):
                            self.feed_details = feed
                            # Check for feed URL
                            if hasattr(feed, "feed_url") and feed.feed_url:
                                self.current_url = feed.feed_url
                                url_input = self.query_one(selector="#feed-url-input", expect_type=Input)
                                url_input.value = self.current_url
                            break
            except Exception as feed_error:
                logger.error(msg=f"Error fetching feed details: {feed_error}")
                self.notify(
                    title="Warning",
                    message="Could not fetch complete feed details. Some settings may not be available.",
                    severity="warning",
                    timeout=5
                )
                # Create minimal feed details with the information we have
                self.feed_details = type('obj', (object,), {
                    'title': self.current_title,
                    'cat_id': 0,  # Default to uncategorized
                    'update_enabled': True,
                    'include_in_digest': True,
                    'always_display_attachments': False,
                    'mark_unread_on_update': False
                })

            if self.feed_details:
                # Update feed values from details
                if hasattr(self.feed_details, "title"):
                    self.current_title = self.feed_details.title # type: ignore
                    self.feed_title = self.feed_details.title # type: ignore
                    title_input: Input = self.query_one(selector="#feed-title-input", expect_type=Input)
                    title_input.value = self.current_title

                # Get current category
                if hasattr(self.feed_details, "cat_id"):
                    self.current_category_id = self.feed_details.cat_id # type: ignore

                    # Select the current category in the list
                    for i, (cat_id, _) in enumerate(self.categories):
                        if int(cat_id) == int(self.current_category_id):
                            category_list.index = i
                            self.selected_category = cat_id
                            break

                # Display feed settings
                settings_container = self.query_one("#settings-container", Vertical)
                # Remove previous children
                await settings_container.remove_children()

                # Add toggles for common feed settings
                settings = [
                    (
                        "update-enabled",
                        "Enable Updates",
                        getattr(self.feed_details, "update_enabled", True),
                    ),
                    (
                        "include-in-digest",
                        "Include in Digest",
                        getattr(self.feed_details, "include_in_digest", True),
                    ),
                    (
                        "always-display-attachments",
                        "Always Display Attachments",
                        getattr(self.feed_details, "always_display_attachments", False),
                    ),
                    (
                        "mark-unread-on-update",
                        "Mark Unread on Update",
                        getattr(self.feed_details, "mark_unread_on_update", False),
                    ),
                ]

                # First create all the widgets that will go in the settings container
                setting_widgets = []
                for setting_id, label_text, value in settings:
                    # Create a horizontal container for each setting with its checkbox and label
                    container = Horizontal(id=f"setting-{setting_id}")
                    # Add the checkbox and label as its children in the constructor
                    container.compose_add_child(Checkbox(value=value, id=f"checkbox-{setting_id}"))
                    container.compose_add_child(Label(label_text))
                    # Add to our list of widgets to mount
                    setting_widgets.append(container)

                # Now mount all the widgets at once
                if setting_widgets:
                    await settings_container.mount(*setting_widgets)

            # Hide progress indicator
            progress_container.styles.display = "none"
            self._loading = False

        except Exception as e:
            # Hide progress indicator if there's an error
            if self._loading:
                progress_container = self.query_one("#progress-container", Vertical)
                progress_container.styles.display = "none"
                self._loading = False

            logger.error(f"Error loading feed details: {e}")
            self.notify(
                title="Error",
                message=f"Failed to load feed details: {e}",
                severity="error",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "save-button":
            self.action_save_feed()
        elif event.button.id == "cancel-button":
            self.action_close_screen()
        elif event.button.id == "delete-button":
            self.action_confirm_delete()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update variables when input changes."""
        if event.input.id == "feed-title-input":
            self.feed_title = event.value

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle category selection."""
        if event.list_view.id == "category-list" and event.list_view.index is not None:
            self.selected_category = self.categories[event.list_view.index][0]

    def action_save_feed(self) -> None:
        """Save the feed with updated properties."""
        try:
            # Show progress indicator
            progress_container = self.query_one("#progress-container", Vertical)
            progress_container.styles.display = "block"
            self._loading = True

            # Collect settings from checkboxes
            settings = {}
            for setting_id in [
                "update-enabled",
                "include-in-digest",
                "always-display-attachments",
                "mark-unread-on-update",
            ]:
                checkbox = self.query_one(f"#checkbox-{setting_id}", Checkbox)
                settings[setting_id.replace("-", "_")] = checkbox.value

            # Update the feed
            result = self.client.update_feed_properties(
                feed_id=self.feed_id,
                title=self.feed_title,
                category_id=self.selected_category,
                **settings,
            )

            # Hide progress indicator
            progress_container.styles.display = "none"
            self._loading = False

            if result and getattr(result, "status", False):
                self.notify(message="Feed updated successfully", title="Success")
                self.dismiss(result=True)
            else:
                self.notify(
                    message=f"Failed to update feed: {getattr(result, 'message', 'Unknown error')}",
                    title="Error",
                    severity="error",
                )
        except Exception as e:
            # Hide progress indicator if there's an error
            if self._loading:
                progress_container = self.query_one("#progress-container", Vertical)
                progress_container.styles.display = "none"
                self._loading = False

            logger.error(msg=f"Error updating feed: {e}")
            self.notify(
                message=f"Error updating feed: {e}", title="Error", severity="error"
            )

    def action_confirm_delete(self) -> None:
        """Show confirmation dialog before deleting feed."""
        # We'll show a simple confirm dialog within this screen
        # instead of pushing a new screen
        self.app.push_screen(
            ConfirmScreen(
                title="Delete Feed",
                message=f"Are you sure you want to delete the feed '{self.current_title}'?",
                on_confirm=self.delete_feed,
            )
        )

    def delete_feed(self) -> None:
        """Delete the feed after confirmation."""
        try:
            # Show progress indicator
            progress_container = self.query_one("#progress-container", Vertical)
            progress_container.styles.display = "block"
            self._loading = True

            # Delete the feed
            result = self.client.unsubscribe_feed(feed_id=self.feed_id)

            # Hide progress indicator
            progress_container.styles.display = "none"
            self._loading = False

            if result and getattr(result, "status", False):
                self.notify(message="Feed deleted successfully", title="Success")
                self.dismiss(result={"action": "deleted", "feed_id": self.feed_id})
            else:
                self.notify(
                    message=f"Failed to delete feed: {getattr(result, 'message', 'Unknown error')}",
                    title="Error",
                    severity="error",
                )
        except Exception as e:
            # Hide progress indicator if there's an error
            if self._loading:
                progress_container = self.query_one("#progress-container", Vertical)
                progress_container.styles.display = "none"
                self._loading = False

            logger.error(msg=f"Error deleting feed: {e}")
            self.notify(
                message=f"Error deleting feed: {e}", title="Error", severity="error"
            )

    def action_close_screen(self) -> None:
        """Close the screen."""
        self.dismiss(result=False)