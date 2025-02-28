"""Test for ttrsscli module."""
import subprocess
from unittest.mock import MagicMock, patch

from ttrss.client import Article, Category, Feed, Headline

from ttrsscli.ttrsscli import LimitedSizeDict, TTRSSClient, get_conf_value


class TestLimitedSizeDict:
    """Test for LimitedSizeDict."""

    def test_initialization(self) -> None:
        """Test that the dictionary initializes correctly."""
        limited_dict = LimitedSizeDict(max_size=3)
        assert limited_dict.max_size == 3
        assert len(limited_dict) == 0

    def test_add_items_within_limit(self) -> None:
        """Test adding items within the size limit."""
        limited_dict = LimitedSizeDict(max_size=3)
        limited_dict["a"] = 1
        limited_dict["b"] = 2
        assert len(limited_dict) == 2
        assert "a" in limited_dict
        assert "b" in limited_dict
        assert limited_dict["a"] == 1
        assert limited_dict["b"] == 2

    def test_add_items_exceeding_limit(self) -> None:
        """Test adding items that exceed the size limit."""
        limited_dict = LimitedSizeDict(max_size=3)
        limited_dict["a"] = 1
        limited_dict["b"] = 2
        limited_dict["c"] = 3
        limited_dict["d"] = 4
        assert len(limited_dict) == 3
        assert "a" not in limited_dict
        assert "b" in limited_dict
        assert "c" in limited_dict
        assert "d" in limited_dict
        assert limited_dict["b"] == 2
        assert limited_dict["c"] == 3
        assert limited_dict["d"] == 4

    def test_add_existing_item(self) -> None:
        """Test adding an existing item."""
        limited_dict = LimitedSizeDict(max_size=3)
        limited_dict["a"] = 1
        limited_dict["b"] = 2
        limited_dict["a"] = 3
        assert len(limited_dict) == 2
        assert "a" in limited_dict
        assert "b" in limited_dict
        assert limited_dict["a"] == 3

    def test_add_existing_item_exceeds_limit(self) -> None:
        """Test adding an existing item when exceeding size limit."""
        limited_dict = LimitedSizeDict(max_size=3)
        limited_dict["a"] = 1
        limited_dict["b"] = 2
        limited_dict["c"] = 3
        limited_dict["a"] = 4
        assert len(limited_dict) == 3
        assert "a" in limited_dict
        assert "b" in limited_dict
        assert "c" in limited_dict
        assert limited_dict["a"] == 4
        limited_dict["d"] = 5
        assert "b" not in limited_dict
        assert "a" in limited_dict

    def test_order_maintained(self) -> None:
        """Test that the order is maintained when adding items."""
        limited_dict = LimitedSizeDict(max_size=3)
        limited_dict["a"] = 1
        limited_dict["b"] = 2
        limited_dict["c"] = 3

        assert list(limited_dict.keys()) == ["a", "b", "c"]

        limited_dict["a"] = 4
        assert list(limited_dict.keys()) == ["b", "c", "a"]

        limited_dict["d"] = 5
        assert list(limited_dict.keys()) == ["c", "a", "d"]


class TestGetConfValue:
    """Test for get_conf_value."""

    @patch("subprocess.run")
    def test_get_conf_value_op_command_success(self, mock_run) -> None:
        """Test get_conf_value with a successful 'op' command."""
        mock_result = MagicMock()
        mock_result.stdout = "test_value\n"
        mock_result.stderr = ""
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        op_command = "op read op://vault/item/field"
        result: str = get_conf_value(op_command=op_command)

        mock_run.assert_called_once_with(
            args=["op", "read", "op://vault/item/field"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result == "test_value"

    @patch("subprocess.run")
    def test_get_conf_value_op_command_called_process_error(
        self, mock_run, caplog
    ) -> None:
        """Test get_conf_value with a failing 'op' command (CalledProcessError)."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd="op read op://vault/item/field"
        )
        op_command = "op read op://vault/item/field"

        with patch("sys.exit") as mock_exit, patch("builtins.print") as mock_print:
            get_conf_value(op_command=op_command)

        mock_run.assert_called_once_with(
            args=["op", "read", "op://vault/item/field"],
            capture_output=True,
            text=True,
            check=True,
        )
        mock_print.assert_called_once()
        mock_exit.assert_called_once_with(1)
        assert "Error executing command" in caplog.text

    @patch("subprocess.run")
    def test_get_conf_value_op_command_file_not_found_error(
        self, mock_run, caplog
    ) -> None:
        """Test get_conf_value when 'op' command not found (FileNotFoundError)."""
        mock_run.side_effect = FileNotFoundError()
        op_command = "op read op://vault/item/field"

        with patch("sys.exit") as mock_exit, patch("builtins.print") as mock_print:
            get_conf_value(op_command=op_command)

        mock_print.assert_called_once()
        mock_exit.assert_called_once_with(1)
        assert "Error: 'op' command not found." in caplog.text

    @patch("subprocess.run")
    def test_get_conf_value_op_command_name_resolution_error(
        self, mock_run, caplog
    ) -> None:
        """Test get_conf_value with NameResolutionError."""
        from urllib3.exceptions import NameResolutionError

        mock_run.side_effect = NameResolutionError(
            None, "mock_host", "mock_url"
        )

        op_command = "op read op://vault/item/field"

        with patch("sys.exit") as mock_exit, patch("builtins.print") as mock_print:
            get_conf_value(op_command=op_command)

        mock_print.assert_called_once()
        mock_exit.assert_called_once_with(1)
        assert "Error: Couldn't look up server for url." in caplog.text

    def test_get_conf_value_plain_string(self) -> None:
        """Test get_conf_value with a plain string (no 'op' command)."""
        op_command = "plain_value"
        result: str = get_conf_value(op_command=op_command)
        assert result == "plain_value"

