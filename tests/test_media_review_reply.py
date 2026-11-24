"""Tests for photo review inside the DingTalk message pipeline.

Every case runs offline: the gateway is replaced by a delayed fake reviewer and
replies are captured from ``PipelineHandler.reply_text``. No test reads or
mutates ``os.environ``.
"""

import asyncio
import logging

import pytest
from dingtalk_stream import CallbackMessage
from unittest.mock import AsyncMock, MagicMock

from app.handlers.message import (
    MediaFileHandler,
    PipelineHandler,
    REVIEW_PREFIX,
    _ReviewBatch,
    _format_reviews,
)
from app.services.file_downloader import DownloadResult


class _DelayedReviewer:
    """Fake reviewer with deterministic results and optional delay."""

    def __init__(self, results=None, delay=0.0, block=None):
        self._results = list(results or [])
        self._delay = delay
        self._block = block
        self.calls = []

    async def review(self, image_path):
        self.calls.append(image_path)
        # Consume the result before awaiting so concurrent tasks keep the
        # order in which the handler started them.
        text = self._results.pop(0) if self._results else None
        if self._block is not None:
            await self._block.wait()
        if self._delay:
            await asyncio.sleep(self._delay)
        return text


def _build_handler(
    tmp_path,
    reviewer,
    merge_window=1.0,
    review_timeout=5.0,
    logger=None,
    download=None,
):
    output_dir = tmp_path / "output"
    counter = {"n": 0}

    async def default_download(_url):
        counter["n"] += 1
        path = tmp_path / f"temp_{counter['n']}.bin"
        path.write_bytes(b"not really an image")
        return DownloadResult(
            temp_path=str(path),
            sha256=f"sha-{counter['n']}",
            file_size=19,
        )

    downloader = MagicMock()
    downloader.get_download_url = AsyncMock(return_value="https://example.com/dl")
    downloader.download_file_stream = download or default_download

    store = MagicMock()
    store.async_is_duplicate = AsyncMock(return_value=False)
    store.async_insert_record = AsyncMock(return_value=1)

    handler = MediaFileHandler(
        output_dir=str(output_dir),
        metadata_store=store,
        file_downloader=downloader,
        logger=logger,
        reviewer=reviewer,
        review_merge_window=merge_window,
        review_timeout=review_timeout,
    )
    pipeline = PipelineHandler(handlers=[handler])
    replies = []

    def fake_reply_text(text, _message):
        replies.append(text)
        return {"errcode": 0}

    pipeline.reply_text = fake_reply_text
    return handler, pipeline, replies


def _callback(msgtype, content, conversation_type="1"):
    callback = CallbackMessage()
    callback.data = {
        "msgtype": msgtype,
        "senderNick": "Alice",
        "senderId": "user_001",
        "senderStaffId": "staff-001",
        "sessionWebhook": "https://webhook.mock",
        "conversationType": conversation_type,
        "content": content,
    }
    return callback


async def _wait_for_reviews(handler):
    """Wait until no review task is left (including deferred follow-ups)."""
    while handler._review_tasks:
        await asyncio.gather(*list(handler._review_tasks), return_exceptions=True)
        await asyncio.sleep(0)


# --- reply formatting ------------------------------------------------------


def test_format_reviews_returns_none_when_empty():
    assert _format_reviews({}) is None


def test_format_reviews_keeps_single_review_unlabelled():
    assert _format_reviews({2: "很棒"}) == "很棒"


def test_format_reviews_labels_multiple_in_image_order():
    assert _format_reviews({3: "c", 1: "a"}) == "图1：a\n图3：c"


# --- review batch ----------------------------------------------------------


@pytest.mark.asyncio
async def test_review_batch_wait_keeps_stragglers_running():
    gate = asyncio.Event()

    class Reviewer:
        async def review(self, path):
            if path == "slow":
                await gate.wait()
                return "SLOW"
            return "FAST"

    batch = _ReviewBatch(Reviewer(), [(1, "fast"), (2, "slow")], total_timeout=1.0)
    batch.start()

    reviews, pending = await batch.wait(0.01)

    assert reviews == {1: "FAST"}
    assert len(pending) == 1

    gate.set()
    assert await batch.finish() == {1: "FAST", 2: "SLOW"}


@pytest.mark.asyncio
async def test_review_batch_finish_cancels_at_deadline(caplog):
    block = asyncio.Event()

    class Reviewer:
        async def review(self, _path):
            await block.wait()
            return "late"

    batch = _ReviewBatch(
        Reviewer(),
        [(1, "photo")],
        total_timeout=0.02,
        logger=logging.getLogger("file-bridge.test.review"),
    )
    batch.start()

    with caplog.at_level(logging.WARNING, logger="file-bridge.test.review"):
        assert await batch.finish() == {}

    assert "cancelled after" in caplog.text


@pytest.mark.asyncio
async def test_review_batch_deadline_is_fixed_at_first_request():
    class Reviewer:
        async def review(self, _path):
            return "ok"

    batch = _ReviewBatch(Reviewer(), [], total_timeout=1.0)
    batch.add(1, "first")
    deadline = batch._deadline

    # A later request (e.g. a slow group-chat download) must not extend the
    # batch's shared deadline.
    batch.add(2, "second")
    batch.start()

    assert deadline > 0
    assert batch._deadline == deadline
    await asyncio.gather(*batch._tasks, return_exceptions=True)


# --- single photo ----------------------------------------------------------


@pytest.mark.asyncio
async def test_review_within_window_merges_into_one_reply(tmp_path):
    reviewer = _DelayedReviewer(results=["构图很棒"])
    handler, pipeline, replies = _build_handler(tmp_path, reviewer)

    await pipeline.process(
        _callback("picture", {"downloadCode": "code-1"})
    )
    await _wait_for_reviews(handler)

    assert len(replies) == 1
    assert "文件接收成功，已保存为:" in replies[0]
    assert replies[0].endswith("构图很棒")
    assert not replies[0].startswith(REVIEW_PREFIX)
    assert len(reviewer.calls) == 1


@pytest.mark.asyncio
async def test_review_after_window_is_sent_as_prefixed_second_message(tmp_path):
    reviewer = _DelayedReviewer(results=["构图很棒"], delay=0.1)
    handler, pipeline, replies = _build_handler(
        tmp_path, reviewer, merge_window=0.01, review_timeout=1.0
    )

    await pipeline.process(_callback("picture", {"downloadCode": "code-1"}))

    # The first reply is already delivered and carries no review.
    assert len(replies) == 1
    assert "构图很棒" not in replies[0]

    await _wait_for_reviews(handler)

    assert len(replies) == 2
    assert replies[1].startswith(REVIEW_PREFIX)
    assert "构图很棒" in replies[1]


@pytest.mark.asyncio
async def test_review_total_timeout_sends_only_one_reply(tmp_path, caplog):
    block = asyncio.Event()
    reviewer = _DelayedReviewer(results=["太晚了"], block=block)
    logger = logging.getLogger("file-bridge.test.review")
    handler, pipeline, replies = _build_handler(
        tmp_path,
        reviewer,
        merge_window=0.01,
        review_timeout=0.05,
        logger=logger,
    )

    with caplog.at_level(logging.WARNING, logger="file-bridge.test.review"):
        await pipeline.process(_callback("picture", {"downloadCode": "code-1"}))
        await _wait_for_reviews(handler)

    assert len(replies) == 1
    assert "太晚了" not in replies[0]
    assert "cancelled after" in caplog.text


@pytest.mark.asyncio
async def test_review_failure_keeps_the_existing_single_reply(tmp_path):
    reviewer = _DelayedReviewer(results=[None])
    handler, pipeline, replies = _build_handler(tmp_path, reviewer)

    await pipeline.process(_callback("picture", {"downloadCode": "code-1"}))
    await _wait_for_reviews(handler)

    assert len(replies) == 1
    assert "文件接收成功，已保存为:" in replies[0]
    assert REVIEW_PREFIX not in replies[0]


@pytest.mark.asyncio
async def test_video_and_file_are_never_reviewed(tmp_path):
    reviewer = _DelayedReviewer(results=["不应出现"])
    handler, pipeline, replies = _build_handler(tmp_path, reviewer)

    await pipeline.process(_callback("video", {"downloadCode": "video-1"}))
    await pipeline.process(_callback("file", {"downloadCode": "file-1"}))
    await _wait_for_reviews(handler)

    assert len(replies) == 2
    assert all(REVIEW_PREFIX not in text for text in replies)
    assert reviewer.calls == []


# --- group chat (richText) -------------------------------------------------


def _rich_text(segments):
    return {"richText": [{"downloadCode": code} for code in segments]}


@pytest.mark.asyncio
async def test_group_reviews_merge_into_one_labelled_message(tmp_path):
    reviewer = _DelayedReviewer(results=["a", "b", "c"])
    handler, pipeline, replies = _build_handler(tmp_path, reviewer)

    await pipeline.process(
        _callback("richText", _rich_text(["c1", "c2", "c3"]), conversation_type="2")
    )
    await _wait_for_reviews(handler)

    assert len(replies) == 1
    assert "图1：a" in replies[0]
    assert "图2：b" in replies[0]
    assert "图3：c" in replies[0]
    assert REVIEW_PREFIX not in replies[0]


@pytest.mark.asyncio
async def test_group_reviews_start_before_later_downloads_finish(tmp_path):
    first_review = asyncio.Event()

    class Reviewer:
        def __init__(self):
            self.calls = []

        async def review(self, path):
            self.calls.append(path)
            first_review.set()
            return "ok"

    reviewer = Reviewer()
    counter = {"n": 0}

    async def download(_url):
        counter["n"] += 1
        if counter["n"] == 2:
            # If reviews only started after the whole batch was saved, this
            # would deadlock until the timeout.
            await asyncio.wait_for(first_review.wait(), timeout=1.0)
        path = tmp_path / f"temp_{counter['n']}.bin"
        path.write_bytes(b"not really an image")
        return DownloadResult(
            temp_path=str(path),
            sha256=f"sha-{counter['n']}",
            file_size=19,
        )

    handler, pipeline, replies = _build_handler(
        tmp_path, reviewer, download=download
    )

    await pipeline.process(
        _callback("richText", _rich_text(["c1", "c2"]), conversation_type="2")
    )
    await _wait_for_reviews(handler)

    assert len(reviewer.calls) == 2
    assert len(replies) == 1
    assert "图1：ok" in replies[0]
    assert "图2：ok" in replies[0]


@pytest.mark.asyncio
async def test_group_partial_failure_omits_the_failed_image(tmp_path):
    reviewer = _DelayedReviewer(results=["a", None, "c"], delay=0.1)
    handler, pipeline, replies = _build_handler(
        tmp_path, reviewer, merge_window=0.01, review_timeout=1.0
    )

    await pipeline.process(
        _callback("richText", _rich_text(["c1", "c2", "c3"]), conversation_type="2")
    )
    await _wait_for_reviews(handler)

    assert len(replies) == 2
    followup = replies[1]
    assert followup.startswith(REVIEW_PREFIX)
    assert "图1：a" in followup
    assert "图3：c" in followup
    assert "图2：" not in followup


@pytest.mark.asyncio
async def test_group_all_failures_send_no_followup(tmp_path):
    reviewer = _DelayedReviewer(results=[None, None])
    handler, pipeline, replies = _build_handler(
        tmp_path, reviewer, merge_window=0.01, review_timeout=1.0
    )

    await pipeline.process(
        _callback("richText", _rich_text(["c1", "c2"]), conversation_type="2")
    )
    await _wait_for_reviews(handler)

    assert len(replies) == 1
    assert REVIEW_PREFIX not in replies[0]


@pytest.mark.asyncio
async def test_group_without_saved_images_starts_no_review(tmp_path):
    reviewer = _DelayedReviewer(results=["a"])
    handler, pipeline, replies = _build_handler(tmp_path, reviewer)

    await pipeline.process(
        _callback("richText", {"richText": [{"text": "只发文字"}]}, conversation_type="2")
    )
    await _wait_for_reviews(handler)

    assert replies == []
    assert reviewer.calls == []


# --- disabled review and shutdown -----------------------------------------


@pytest.mark.asyncio
async def test_disabled_review_keeps_single_reply(tmp_path):
    handler, pipeline, replies = _build_handler(tmp_path, reviewer=None)

    await pipeline.process(_callback("picture", {"downloadCode": "code-1"}))

    assert len(replies) == 1
    assert "文件接收成功，已保存为:" in replies[0]
    assert handler._review_tasks == set()


@pytest.mark.asyncio
async def test_disable_review_stops_reviews_after_probe_failure(tmp_path):
    reviewer = _DelayedReviewer(results=["a"])
    handler, pipeline, replies = _build_handler(tmp_path, reviewer)

    handler.disable_review()
    await pipeline.process(_callback("picture", {"downloadCode": "code-1"}))
    await _wait_for_reviews(handler)

    assert len(replies) == 1
    assert reviewer.calls == []


@pytest.mark.asyncio
async def test_cancel_tasks_drops_the_deferred_review(tmp_path):
    block = asyncio.Event()
    reviewer = _DelayedReviewer(results=["a"], block=block)
    handler, pipeline, replies = _build_handler(
        tmp_path, reviewer, merge_window=0.01, review_timeout=5.0
    )

    await pipeline.process(_callback("picture", {"downloadCode": "code-1"}))
    assert len(replies) == 1

    handler.cancel_tasks()
    await _wait_for_reviews(handler)

    assert len(replies) == 1
