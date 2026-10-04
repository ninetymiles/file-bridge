"""Command matcher backends and the startup selection factory."""

import logging

from .base import BaseCommandMatcher, is_inquiry_text, normalize_command_text
from .catalog import COMMAND_CATALOG, REBUILD_INDEX
from .substring import SubstringCommandMatcher

__all__ = [
    "BaseCommandMatcher",
    "COMMAND_CATALOG",
    "REBUILD_INDEX",
    "SubstringCommandMatcher",
    "is_inquiry_text",
    "normalize_command_text",
    "parse_enabled",
    "build_command_matcher",
]

logger = logging.getLogger("file-bridge")
_ENABLED_VALUES = frozenset({"true", "1"})


def parse_enabled(raw: str | None) -> bool:
    """Interpret a boolean-ish opt-in value (case-insensitive true/1)."""
    return raw is not None and raw.strip().lower() in _ENABLED_VALUES


def build_command_matcher(enabled: bool) -> BaseCommandMatcher:
    """Select the command backend from an explicit startup flag."""
    if not enabled:
        logger.info("Command matcher initialized: substring")
        return SubstringCommandMatcher()

    # Loaded only on the opt-in branch so the default path never imports the
    # native inference stack; construction failures propagate and fail startup.
    from .semantic import MODEL_NAME, MATCH_THRESHOLD, FastEmbedEmbedder, SemanticCommandMatcher

    matcher = SemanticCommandMatcher(FastEmbedEmbedder())
    logger.info(
        "Command matcher initialized: semantic (model=%s, threshold=%.2f)",
        MODEL_NAME,
        MATCH_THRESHOLD,
    )
    return matcher
