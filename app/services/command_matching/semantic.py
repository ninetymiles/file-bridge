"""Embedding-based semantic command matcher (fastembed / ONNX Runtime).

Importing this module loads the fastembed native stack, so the package factory
imports it only when SEMANTIC_COMMAND_ENABLED opts into the semantic backend.
"""

import asyncio
import os
from collections.abc import Mapping
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding

from .base import BaseCommandMatcher
from .catalog import COMMAND_CATALOG

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
MATCH_THRESHOLD = 0.8
# This file is app/services/command_matching/semantic.py, so parents[3] is the
# project root (/app in the image). Anchor on __file__, not cwd, so pytest and
# other entrypoints always resolve the same project-local cache directory.
DEFAULT_MODEL_CACHE_DIR = Path(__file__).resolve().parents[3] / "cache"


def resolve_model_cache_dir() -> Path:
    # An explicit env value still wins (custom paths / offline distribution);
    # without it the project cache is used instead of the system temp dir.
    return Path(os.getenv("FASTEMBED_CACHE_PATH") or DEFAULT_MODEL_CACHE_DIR)


class FastEmbedEmbedder:
    """Thin boundary over fastembed: texts in, L2-normalized vectors out."""

    def __init__(self, model_name: str = MODEL_NAME):
        self._model = TextEmbedding(
            model_name=model_name,
            cache_dir=str(resolve_model_cache_dir()),
        )

    def embed(self, texts: list[str]) -> np.ndarray:
        # The builtin fastembed ONNX pipeline applies pooling and L2
        # normalization itself, so dot products equal cosine similarity.
        return np.stack(list(self._model.embed(texts)))


class SemanticCommandMatcher(BaseCommandMatcher):
    """Match by maximum cosine similarity against embedded catalog phrases."""

    def __init__(
        self,
        embedder: FastEmbedEmbedder,
        catalog: Mapping[str, tuple[str, ...]] = COMMAND_CATALOG,
        threshold: float = MATCH_THRESHOLD,
    ):
        self._phrases = [
            (command_id, phrase)
            for command_id, synonyms in catalog.items()
            for phrase in synonyms
        ]
        self._embedder = embedder
        self._threshold = threshold
        # Command phrases are short symmetric texts; bge-small-zh needs no
        # query/passage instruction prefix. Vectors are embedded once at
        # startup and held in memory.
        self._phrase_vectors = embedder.embed([phrase for _, phrase in self._phrases])

    async def match(self, text: str) -> str | None:
        return await asyncio.to_thread(self._match_blocking, text)

    def _match_blocking(self, text: str) -> str | None:
        query_vector = self._embedder.embed([text])[0]
        scores = self._phrase_vectors @ query_vector
        best_index = int(np.argmax(scores))
        if scores[best_index] >= self._threshold:
            return self._phrases[best_index][0]
        return None
