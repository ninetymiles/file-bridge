"""Command matcher backends and the startup selection factory."""

import logging
import os

from .base import BaseCommandMatcher, normalize_command_text
from .catalog import COMMAND_CATALOG, REBUILD_INDEX
from .substring import SubstringCommandMatcher

__all__ = [
    "BaseCommandMatcher",
    "COMMAND_CATALOG",
    "REBUILD_INDEX",
    "SubstringCommandMatcher",
    "normalize_command_text",
    "build_command_matcher",
]

logger = logging.getLogger("file-bridge")
_ENABLED_VALUES = frozenset({"true", "1"})


def build_command_matcher() -> BaseCommandMatcher:
    """Select the command backend from SEMANTIC_COMMAND_ENABLED at startup."""
    enabled = os.getenv("SEMANTIC_COMMAND_ENABLED", "").strip().lower() in _ENABLED_VALUES
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
