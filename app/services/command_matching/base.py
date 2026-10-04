"""Abstract command matcher contract and shared text normalization."""

import re
from abc import ABC, abstractmethod

_IMG_PLACEHOLDER_PATTERN = re.compile(r"<img\d+>")

# Inquiry/interrogative markers. Embedding similarity cannot reliably tell an
# action command ("更新索引") from a status inquiry about it ("更新索引了吗"),
# so texts flagged as inquiries are short-circuited before the matcher.
# Strong end-of-sentence interrogative signals:
_INQUIRY_SUFFIXES: tuple[str, ...] = (
    "完成了吗",
    "好了吗",
    "了吗",
    "怎么样",
    "吗",
)
# Quantity/status inquiry tokens that can appear mid-sentence or at the end
# ("现在有多少索引", "查询索引状态"). Commands rarely carry these words.
_INQUIRY_TOKENS: tuple[str, ...] = ("多少", "状态")


def normalize_command_text(text: str) -> str:
    """Strip richText image placeholders and collapse all whitespace runs."""
    return " ".join(_IMG_PLACEHOLDER_PATTERN.sub(" ", text).split())


def is_inquiry_text(normalized_text: str) -> bool:
    """Return True when the normalized text reads as an inquiry.

    Flags texts ending in an interrogative suffix or containing a quantity
    interrogative. Input is expected to be already normalized (whitespace
    collapsed, no leading/trailing space).
    """
    if normalized_text.endswith(_INQUIRY_SUFFIXES):
        return True
    return any(token in normalized_text for token in _INQUIRY_TOKENS)


class BaseCommandMatcher(ABC):
    """Resolves a normalized command text to a command id."""

    @abstractmethod
    async def match(self, text: str) -> str | None:
        """Return the matched command id, or None when no command is found."""
