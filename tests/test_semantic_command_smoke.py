"""Real-model acceptance for the semantic command matcher.

Runs only with ``pytest -m semantic``. Constructs the real fastembed backend
directly (no factory, no SEMANTIC_COMMAND_ENABLED); when the model is neither
cached nor downloadable, construction fails and this module fails outright.
"""

import sys

import pytest

from app.services.command_matching import (
    REBUILD_INDEX,
    is_inquiry_text,
    normalize_command_text,
)

pytestmark = pytest.mark.semantic

POSITIVE_SAMPLES = [
    "重建索引",
    " 重建索引 ",
    "重建索引\n<img1>",
    "请重建索引",
    "帮我重建一下索引",
    "重新建立索引",
    "重新生成文件索引",
    "重新构建一下索引",
    "索引重新建一下",
    "刷新一下索引",
    # Verify/sync phrasings added for the consistency-check intent.
    "检查索引",
    "校验索引",
    "检查文件索引",
    "同步索引",
    "同步文件索引",
    "刷新索引",
    "刷新文件索引",
    "更新索引",
]

# Unrelated texts that the bare matcher itself must reject (below threshold).
NEGATIVE_SAMPLES = [
    "帮我索引一下这个文件",
    "建立文件夹",
    "你好",
    "下载这个文件",
    "把这份文件发给我",
]

# High-overlap status inquiries. The embedding matcher cannot tell these from
# an action command (they score above threshold), so they are intercepted by
# is_inquiry_text in the handler BEFORE the matcher runs. The bare matcher is
# expected to match them; we assert the inquiry guard catches them instead.
INQUIRY_SAMPLES = [
    "查询索引状态",
    "现在有多少索引",
    "索引重建完成了吗",
    "重新构建索引了吗",
    "刷新索引完成了吗",
    "更新索引了吗",
    "索引同步好了吗",
]


@pytest.fixture(scope="module")
def matcher():
    # Collection imports every test file, so the general-suite fastembed stub
    # may already occupy sys.modules. Drop it (and the stub-bound backend
    # module) so the real inference stack is bound at test runtime only.
    if getattr(sys.modules.get("fastembed"), "_file_bridge_test_stub", False):
        sys.modules.pop("fastembed")
        sys.modules.pop("app.services.command_matching.semantic", None)

    from app.services.command_matching.semantic import (
        FastEmbedEmbedder,
        SemanticCommandMatcher,
    )

    return SemanticCommandMatcher(FastEmbedEmbedder())


def test_embedding_dimension(matcher):
    # One row per catalog phrase; bge-small-zh-v1.5 emits 512-dim vectors.
    assert matcher._phrase_vectors.shape[1] == 512


@pytest.mark.asyncio
async def test_positive_samples_match(matcher):
    misses = []
    for sample in POSITIVE_SAMPLES:
        command_id = await matcher.match(normalize_command_text(sample))
        if command_id != REBUILD_INDEX:
            misses.append(sample)
    assert len(misses) <= 1, f"positive samples missed: {misses}"


@pytest.mark.asyncio
async def test_negative_samples_do_not_match(matcher):
    false_hits = []
    for sample in NEGATIVE_SAMPLES:
        command_id = await matcher.match(normalize_command_text(sample))
        if command_id is not None:
            false_hits.append((sample, command_id))
    assert len(false_hits) <= 1, f"negative samples falsely matched: {false_hits}"


def test_inquiry_samples_intercepted_before_matcher():
    # These inquiries score above the matcher's threshold, so the handler must
    # short-circuit them via is_inquiry_text before the matcher ever runs.
    not_flagged = [
        sample for sample in INQUIRY_SAMPLES
        if not is_inquiry_text(normalize_command_text(sample))
    ]
    assert not not_flagged, f"inquiries not intercepted by guard: {not_flagged}"
