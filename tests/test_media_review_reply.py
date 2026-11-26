"""Tests for photo review inside the DingTalk message pipeline.

Every case runs offline: the gateway is replaced by a delayed fake reviewer and
replies are captured from ``PipelineHandler.reply_text``. No test reads or
mutates ``os.environ``.
"""

import asyncio

import pytest
from dingtalk_stream import CallbackMessage
from unittest.mock import AsyncMock, MagicMock

from app.handlers.message import (
    MediaFileHandler,
    PipelineHandler,
    REVIEW_PREFIX,
)
from app.services.file_downloader import DownloadResult
from conftest import process_and_wait


class _DelayedReviewer:
    """Fake reviewer with deterministic results and optional delay."""

    def __init__(self, results=None, delay=0.0, block=None):
        self._results = list(results or [])
        self._delay = delay
        self._block = block
        self.calls = []
        self.cancellations = 0
        self.cancelled = asyncio.Event()

    async def review(self, image_path):
        self.calls.append(image_path)
        # Consume the result before awaiting so concurrent tasks keep the
        # order in which the handler started them.
        text = self._results.pop(0) if self._results else None
        try:
            if self._block is not None:
                await self._block.wait()
            if self._delay:
                await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            self.cancellations += 1
            self.cancelled.set()
            raise
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


async def _wait_for_replies(replies, count, timeout=2.0):
    """Wait until *count* replies were delivered, observing only the reply stream."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while len(replies) < count:
        if loop.time() >= deadline:
            raise AssertionError(
                f"expected {count} replies, got {len(replies)}: {replies!r}"
            )
        await asyncio.sleep(0.005)


# --- single photo ----------------------------------------------------------


@pytest.mark.asyncio
async def test_review_within_window_merges_into_one_reply(tmp_path):
    reviewer = _DelayedReviewer(results=["构图很棒"])
    handler, pipeline, replies = _build_handler(tmp_path, reviewer)

    await process_and_wait(
        pipeline, _callback("picture", {"downloadCode": "code-1"})
    )
    await _wait_for_replies(replies, 1)

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

    await process_and_wait(pipeline, _callback("picture", {"downloadCode": "code-1"}))

    # The first reply is already delivered and carries no review.
    assert len(replies) == 1
    assert "构图很棒" not in replies[0]

    await _wait_for_replies(replies, 2)

    assert len(replies) == 2
    assert replies[1].startswith(REVIEW_PREFIX)
    assert "构图很棒" in replies[1]


@pytest.mark.asyncio
async def test_review_total_timeout_sends_only_one_reply(tmp_path):
    block = asyncio.Event()
    reviewer = _DelayedReviewer(results=["太晚了"], block=block)
    handler, pipeline, replies = _build_handler(
        tmp_path,
        reviewer,
        merge_window=0.01,
        review_timeout=0.05,
    )

    await process_and_wait(pipeline, _callback("picture", {"downloadCode": "code-1"}))
    await asyncio.wait_for(reviewer.cancelled.wait(), timeout=2.0)

    assert reviewer.cancellations == 1
    assert len(replies) == 1
    assert "太晚了" not in replies[0]


@pytest.mark.asyncio
async def test_review_deadline_is_fixed_at_first_request(tmp_path):
    """A slow later download must not extend the batch's shared deadline.

    The first photo's review blocks while the second download outlives the
    whole review budget. The blocked review is cancelled at the shared
    deadline and its text never reaches the chat.
    """
    block = asyncio.Event()

    class Reviewer:
        def __init__(self):
            self.calls = 0
            self.cancellations = 0
            self.cancelled = asyncio.Event()

        async def review(self, _path):
            self.calls += 1
            if self.calls == 1:
                try:
                    await block.wait()
                except asyncio.CancelledError:
                    self.cancellations += 1
                    self.cancelled.set()
                    raise
                return "first"
            return None

    counter = {"n": 0}

    async def download(_url):
        counter["n"] += 1
        if counter["n"] == 2:
            await asyncio.sleep(0.1)
        path = tmp_path / f"temp_{counter['n']}.bin"
        path.write_bytes(b"not really an image")
        return DownloadResult(
            temp_path=str(path),
            sha256=f"sha-{counter['n']}",
            file_size=19,
        )

    reviewer = Reviewer()
    handler, pipeline, replies = _build_handler(
        tmp_path,
        reviewer,
        merge_window=0.01,
        review_timeout=0.05,
        download=download,
    )

    await process_and_wait(
        pipeline,
        _callback("richText", _rich_text(["c1", "c2"]), conversation_type="2"),
    )
    await asyncio.wait_for(reviewer.cancelled.wait(), timeout=2.0)

    assert reviewer.cancellations == 1
    assert len(replies) == 1
    assert "first" not in replies[0]

    block.set()
    await asyncio.sleep(0.01)

    assert len(replies) == 1


@pytest.mark.asyncio
async def test_review_failure_keeps_the_existing_single_reply(tmp_path):
    reviewer = _DelayedReviewer(results=[None])
    handler, pipeline, replies = _build_handler(tmp_path, reviewer)

    await process_and_wait(pipeline, _callback("picture", {"downloadCode": "code-1"}))
    await _wait_for_replies(replies, 1)

    assert len(replies) == 1
    assert "文件接收成功，已保存为:" in replies[0]
    assert REVIEW_PREFIX not in replies[0]


@pytest.mark.asyncio
async def test_video_and_file_are_never_reviewed(tmp_path):
    reviewer = _DelayedReviewer(results=["不应出现"])
    handler, pipeline, replies = _build_handler(tmp_path, reviewer)

    await process_and_wait(pipeline, _callback("video", {"downloadCode": "video-1"}))
    await process_and_wait(pipeline, _callback("file", {"downloadCode": "file-1"}))
    await _wait_for_replies(replies, 2)

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

    await process_and_wait(
        pipeline,
        _callback("richText", _rich_text(["c1", "c2", "c3"]), conversation_type="2"),
    )
    await _wait_for_replies(replies, 1)

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

    await process_and_wait(
        pipeline,
        _callback("richText", _rich_text(["c1", "c2"]), conversation_type="2"),
    )
    await _wait_for_replies(replies, 1)

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

    await process_and_wait(
        pipeline,
        _callback("richText", _rich_text(["c1", "c2", "c3"]), conversation_type="2"),
    )
    await _wait_for_replies(replies, 2)

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

    await process_and_wait(
        pipeline,
        _callback("richText", _rich_text(["c1", "c2"]), conversation_type="2"),
    )
    await _wait_for_replies(replies, 1)

    assert len(replies) == 1
    assert REVIEW_PREFIX not in replies[0]


@pytest.mark.asyncio
async def test_group_without_saved_images_starts_no_review(tmp_path):
    reviewer = _DelayedReviewer(results=["a"])
    handler, pipeline, replies = _build_handler(tmp_path, reviewer)

    await process_and_wait(
        pipeline,
        _callback("richText", {"richText": [{"text": "只发文字"}]}, conversation_type="2"),
    )

    assert replies == []
    assert reviewer.calls == []


# --- disabled review and shutdown -----------------------------------------


@pytest.mark.asyncio
async def test_disabled_review_keeps_single_reply(tmp_path):
    handler, pipeline, replies = _build_handler(tmp_path, reviewer=None)

    await process_and_wait(pipeline, _callback("picture", {"downloadCode": "code-1"}))

    assert len(replies) == 1
    assert "文件接收成功，已保存为:" in replies[0]


@pytest.mark.asyncio
async def test_disable_review_stops_reviews_after_probe_failure(tmp_path):
    reviewer = _DelayedReviewer(results=["a"])
    handler, pipeline, replies = _build_handler(tmp_path, reviewer)

    handler.disable_review()
    await process_and_wait(pipeline, _callback("picture", {"downloadCode": "code-1"}))
    await _wait_for_replies(replies, 1)

    assert len(replies) == 1
    assert reviewer.calls == []


@pytest.mark.asyncio
async def test_cancel_tasks_drops_the_deferred_review(tmp_path):
    block = asyncio.Event()
    reviewer = _DelayedReviewer(results=["a"], block=block)
    handler, pipeline, replies = _build_handler(
        tmp_path, reviewer, merge_window=0.01, review_timeout=5.0
    )

    await process_and_wait(pipeline, _callback("picture", {"downloadCode": "code-1"}))
    assert len(replies) == 1

    handler.cancel_tasks()
    await asyncio.sleep(0.01)

    assert len(replies) == 1
