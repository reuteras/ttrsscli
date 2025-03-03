"""Cache module for ttrsscli."""

import logging
from collections import OrderedDict

logger: logging.Logger = logging.getLogger(name=__name__)

class LimitedSizeDict(OrderedDict):
    """A dictionary that holds at most 'max_size' items and removes the oldest when full."""

    def __init__(self, max_size: int) -> None:
        """Initialize the LimitedSizeDict.

        Args:
            max_size: Maximum number of items to store in the dictionary
        """
        self.max_size: int = max_size
        super().__init__()

    def __setitem__(self, key, value) -> None:
        """Set an item in the dictionary, removing the oldest if full.

        Args:
            key: Dictionary key
            value: Value to store
        """
        if key in self:
            self.move_to_end(key=key)
        super().__setitem__(key, value)
        if len(self) > self.max_size:
            self.popitem(last=False)