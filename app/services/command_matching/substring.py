"""Substring-based command matcher, standard library only."""

import logging
from collections.abc import Mapping

from .base import BaseCommandMatcher
from .catalog import COMMAND_CATALOG

logger = logging.getLogger("file-bridge.command")


class SubstringCommandMatcher(BaseCommandMatcher):
    """Match when any catalog phrase is literally contained in the text."""

    def __init__(self, catalog: Mapping[str, tuple[str, ...]] = COMMAND_CATALOG):
        self._catalog = list(catalog.items())

    async def match(self, text: str) -> str | None:
        for command_id, phrases in self._catalog:
            if any(phrase in text for phrase in phrases):
                return command_id
        logger.debug("Substring match missed for text: %s", text)
        return None
