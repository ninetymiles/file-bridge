"""Abstract command matcher contract and shared text normalization."""

import re
from abc import ABC, abstractmethod

_IMG_PLACEHOLDER_PATTERN = re.compile(r"<img\d+>")


def normalize_command_text(text: str) -> str:
    """Strip richText image placeholders and collapse all whitespace runs."""
    return " ".join(_IMG_PLACEHOLDER_PATTERN.sub(" ", text).split())


class BaseCommandMatcher(ABC):
    """Resolves a normalized command text to a command id."""

    @abstractmethod
    async def match(self, text: str) -> str | None:
        """Return the matched command id, or None when no command is found."""
