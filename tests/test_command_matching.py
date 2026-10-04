"""Unit tests for command matchers and the matcher selection factory.

The semantic backend module imports fastembed at module top level. General
tests never load the native stack: conftest installs a minimal fastembed stub
before test modules are collected, and only the semantic smoke test (marker
``semantic``) imports the real fastembed in a separate pytest session.
"""

import importlib
import logging
import sys

import numpy as np
import pytest

from app.services.command_matching import (  # noqa: E402
    REBUILD_INDEX,
    SubstringCommandMatcher,
    build_command_matcher,
    is_inquiry_text,
    parse_enabled,
)
from app.services.command_matching.semantic import (  # noqa: E402
    DEFAULT_MODEL_CACHE_DIR,
    FastEmbedEmbedder,
    SemanticCommandMatcher,
)

_SEMANTIC_MODULE_PATH = "app.services.command_matching.semantic"


@pytest.mark.asyncio
async def test_substring_matches_catalog_phrases():
    matcher = SubstringCommandMatcher()
    assert await matcher.match("重建索引") == REBUILD_INDEX
    assert await matcher.match(" 重建索引 ") == REBUILD_INDEX
    assert await matcher.match("请重建索引谢谢") == REBUILD_INDEX
    assert await matcher.match("重新建立索引") == REBUILD_INDEX
    assert await matcher.match("please rebuild index now") == REBUILD_INDEX
    # Verify/sync phrasings added for the consistency-check intent.
    assert await matcher.match("帮我检查索引") == REBUILD_INDEX
    assert await matcher.match("校验索引") == REBUILD_INDEX
    assert await matcher.match("检查文件索引") == REBUILD_INDEX
    assert await matcher.match("同步索引") == REBUILD_INDEX
    assert await matcher.match("同步文件索引") == REBUILD_INDEX
    assert await matcher.match("刷新索引") == REBUILD_INDEX
    assert await matcher.match("刷新文件索引") == REBUILD_INDEX
    assert await matcher.match("更新索引") == REBUILD_INDEX


@pytest.mark.asyncio
async def test_substring_rejects_unrelated_and_empty_text():
    matcher = SubstringCommandMatcher()
    assert await matcher.match("查询索引状态") is None
    assert await matcher.match("帮我索引一下这个文件") is None
    assert await matcher.match("") is None


@pytest.mark.asyncio
async def test_substring_resolves_conflicts_by_catalog_order():
    catalog = {"first": ("索引",), "second": ("重建索引",)}
    matcher = SubstringCommandMatcher(catalog)
    assert await matcher.match("重建索引") == "first"


@pytest.mark.parametrize(
    "text",
    [
        "更新索引了吗",
        "索引同步好了吗",
        "刷新索引完成了吗",
        "现在有多少索引",
        "索引状态怎么样",
        "查询索引状态吗",
        "查询索引状态",
    ],
)
def test_is_inquiry_text_flags_inquiries(text):
    assert is_inquiry_text(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "更新索引",
        "帮我检查索引",
        "重建索引",
        "同步文件索引",
        "",  # empty is not an inquiry; the empty short-circuit handles it
    ],
)
def test_is_inquiry_text_passes_commands(text):
    assert is_inquiry_text(text) is False


class ScriptedEmbedder:
    """Returns fixed passage/query vectors and records raw inputs.

    The first embed call constructs catalog passages; later calls embed one
    user query each, mirroring SemanticCommandMatcher construction order.
    """

    def __init__(self, passage_vectors, query_vectors):
        self._passage_vectors = np.asarray(passage_vectors, dtype=float)
        self._query_vectors = [np.asarray(v, dtype=float) for v in query_vectors]
        self.passage_inputs = None
        self.query_inputs = []

    def embed(self, texts):
        if self.passage_inputs is None:
            self.passage_inputs = list(texts)
            return self._passage_vectors
        self.query_inputs.append(list(texts))
        # Mirror the real backend output shape: one row per input text.
        return np.stack([self._query_vectors.pop(0)])


def _catalog_with_two_commands():
    return {"alpha": ("alpha command",), "beta": ("beta command",)}


@pytest.mark.parametrize("env_mode", ["unset", "empty"])
def test_embedder_defaults_to_project_cache_dir(monkeypatch, env_mode):
    if env_mode == "unset":
        monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
    else:
        monkeypatch.setenv("FASTEMBED_CACHE_PATH", "")

    embedder = FastEmbedEmbedder()

    assert embedder._model.init_kwargs["cache_dir"] == str(DEFAULT_MODEL_CACHE_DIR)
    assert DEFAULT_MODEL_CACHE_DIR.is_absolute()
    assert DEFAULT_MODEL_CACHE_DIR.name == "cache"


def test_embedder_env_overrides_cache_dir(monkeypatch, tmp_path):
    custom_cache = tmp_path / "custom-model-cache"
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(custom_cache))

    embedder = FastEmbedEmbedder()

    assert embedder._model.init_kwargs["cache_dir"] == str(custom_cache)


@pytest.mark.asyncio
async def test_semantic_matches_above_threshold_with_raw_texts():
    embedder = ScriptedEmbedder(
        passage_vectors=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        query_vectors=[[0.99, 0.14, 0.0]],
    )
    matcher = SemanticCommandMatcher(embedder, catalog=_catalog_with_two_commands())

    assert embedder.passage_inputs == ["alpha command", "beta command"]

    assert await matcher.match("跑一下 alpha") == "alpha"
    assert embedder.query_inputs == [["跑一下 alpha"]]


@pytest.mark.asyncio
async def test_semantic_picks_highest_similarity_command():
    embedder = ScriptedEmbedder(
        passage_vectors=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        query_vectors=[[0.14, 0.99, 0.0]],
    )
    matcher = SemanticCommandMatcher(embedder, catalog=_catalog_with_two_commands())
    assert await matcher.match("beta please") == "beta"


@pytest.mark.asyncio
async def test_semantic_rejects_below_threshold():
    embedder = ScriptedEmbedder(
        passage_vectors=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        query_vectors=[[0.707, 0.707, 0.0]],
    )
    matcher = SemanticCommandMatcher(embedder, catalog=_catalog_with_two_commands())
    assert await matcher.match("ambiguous request") is None


class _FakeSemanticMatcher:
    def __init__(self, embedder):
        self.embedder = embedder


class _FailingSemanticMatcher:
    def __init__(self, embedder):
        raise RuntimeError("model unavailable")


class _FakeEmbedder:
    def __init__(self, *args, **kwargs):
        pass


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, False),
        ("", False),
        ("false", False),
        ("0", False),
        ("FALSE", False),
        ("garbage", False),
        (" true ", True),
        ("true", True),
        ("TRUE", True),
        ("1", True),
    ],
)
def test_parse_enabled_interprets_boolish_values(raw, expected):
    assert parse_enabled(raw) is expected


def test_factory_builds_substring_when_disabled(caplog):
    caplog.set_level(logging.INFO, logger="file-bridge")

    matcher = build_command_matcher(False)

    assert isinstance(matcher, SubstringCommandMatcher)
    assert "substring" in caplog.text
    # The opt-out branch never touches a real inference backend.
    assert getattr(sys.modules.get("fastembed"), "_file_bridge_test_stub", False)


def _patch_semantic_backend(monkeypatch, matcher_class):
    semantic_module = importlib.import_module(_SEMANTIC_MODULE_PATH)
    monkeypatch.setattr(semantic_module, "SemanticCommandMatcher", matcher_class)
    monkeypatch.setattr(semantic_module, "FastEmbedEmbedder", _FakeEmbedder)


def test_factory_builds_semantic_when_enabled(monkeypatch, caplog):
    _patch_semantic_backend(monkeypatch, _FakeSemanticMatcher)
    caplog.set_level(logging.INFO, logger="file-bridge")

    matcher = build_command_matcher(True)

    assert isinstance(matcher, _FakeSemanticMatcher)
    assert "semantic" in caplog.text
    assert "BAAI/bge-small-zh-v1.5" in caplog.text


def test_factory_propagates_semantic_construction_failure(monkeypatch):
    _patch_semantic_backend(monkeypatch, _FailingSemanticMatcher)

    with pytest.raises(RuntimeError, match="model unavailable"):
        build_command_matcher(True)
