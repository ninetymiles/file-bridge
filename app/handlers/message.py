"""Message handlers and pipeline implementation for DingTalk stream bot."""

import asyncio
import json
import logging
import os
import random
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, List, Optional, Tuple
import dingtalk_stream
from dingtalk_stream import AckMessage, CallbackMessage, ChatbotMessage

from app.services.command_matching import (
    BaseCommandMatcher,
    is_inquiry_text,
    normalize_command_text,
)
from app.services.disk_warmup import ensure_storage_ready
from app.services.media_metadata import extract_media_metadata
from app.utils.file_storage import save_file

if TYPE_CHECKING:
    from app.services.photo_review import PhotoReviewer


@dataclass
class _ImageProcessResult:
    """Result of processing a single image (download + dedupe + save)."""

    status: str  # "saved" | "duplicate" | "failed" | "cancelled"
    detail: str  # saved filename for "saved", reply message for others
    metadata: Optional[str] = None  # formatted metadata summary line, or None
    saved_path: Optional[str] = None  # absolute path on disk, for photo review


class ReplyTier(IntEnum):
    """Reply delivery priority. Smaller value = higher priority.

    Generic priority semantics only; no coupling to content types.
    Gaps between values allow future tier insertion without renumbering.
    """

    PRIMARY = 100
    SECONDARY = 200


# Photo review timing. The merge window decides whether the review joins the
# first reply; the total timeout bounds how long a follow-up may live; the
# connect timeout only catches a dead gateway. See the message-pipeline spec.
REVIEW_MERGE_WINDOW = 15.0
REVIEW_TOTAL_TIMEOUT = 60.0
REVIEW_CONNECT_TIMEOUT = 5.0
REVIEW_PREFIX = "照片点评："


@dataclass(frozen=True)
class ReplyIntent:
    """Intent to send a reply, produced by a message handler."""

    tier: ReplyTier
    text: str
    # Optional callback run after the pipeline has delivered this reply. It
    # must return promptly; handlers use it to release a follow-up message
    # that must never arrive before the first one.
    after_reply: Optional[Callable[[], None]] = None


def _format_reviews(reviews: dict[int, str]) -> Optional[str]:
    """Render collected reviews, labelled by image order when there are many."""
    entries = [(index, text) for index, text in sorted(reviews.items()) if text]
    if not entries:
        return None
    if len(entries) == 1:
        return entries[0][1]
    return "\n".join(f"图{index}：{text}" for index, text in entries)


class _ReviewBatch:
    """Photo review requests that share one total deadline.

    ``wait`` races the batch against the merge window without cancelling
    stragglers; ``finish`` waits for what is left until the deadline and then
    cancels it. Completed reviews are kept in both paths, so a single stuck
    image never discards the others' results.
    """

    def __init__(
        self,
        reviewer: "PhotoReviewer",
        entries: list[tuple[int, str]],
        *,
        total_timeout: float = REVIEW_TOTAL_TIMEOUT,
        logger: Optional[logging.Logger] = None,
        registry: Optional[set[asyncio.Task]] = None,
    ):
        self.reviewer = reviewer
        self.total_timeout = total_timeout
        self.logger = logger or logging.getLogger(__name__)
        self._registry = registry
        self._entries = list(entries)
        self._tasks: list[asyncio.Task] = []
        self._reviews: dict[int, str] = {}
        self._deadline = 0.0

    def __bool__(self) -> bool:
        return bool(self._tasks or self._entries)

    def add(self, index: int, path: str) -> None:
        """Start one review task; may be called before :meth:`start`.

        The batch deadline starts with the first request, not when the whole
        batch is known: group chats launch reviews as each photo is saved, so
        a slow download must not extend a hung request past the total limit.
        """
        if self._deadline == 0.0:
            self._deadline = asyncio.get_running_loop().time() + self.total_timeout
        task = asyncio.create_task(self._review(index, path))
        self._tasks.append(task)
        if self._registry is not None:
            self._registry.add(task)
            task.add_done_callback(self._registry.discard)

    def start(self) -> None:
        """Create any queued tasks; the deadline may already be running."""
        if not self._tasks:
            for index, path in self._entries:
                self.add(index, path)

    async def _review(self, index: int, path: str) -> tuple[int, Optional[str]]:
        # PhotoReviewer.review() never raises; the guard is for injected fakes
        # and future implementations, so one bad review cannot break the batch.
        try:
            return index, await self.reviewer.review(path)
        except Exception as exc:
            self.logger.warning(
                "Photo review task failed (%s): %s",
                type(exc).__name__,
                str(exc)[:200],
            )
            return index, None

    def _collect(self, tasks) -> None:
        for task in tasks:
            if task.cancelled():
                continue
            try:
                index, text = task.result()
            except Exception:
                continue
            if text:
                self._reviews[index] = text

    async def wait(
        self, timeout: float
    ) -> tuple[dict[int, str], list[asyncio.Task]]:
        """Race the batch against *timeout*, leaving stragglers running."""
        if not self._tasks:
            return {}, []
        done, pending = await asyncio.wait(self._tasks, timeout=timeout)
        self._collect(done)
        return dict(self._reviews), list(pending)

    async def finish(self) -> dict[int, str]:
        """Wait for stragglers until the batch deadline, then cancel them."""
        if not self._tasks:
            return {}
        pending = [task for task in self._tasks if not task.done()]
        if pending:
            loop = asyncio.get_running_loop()
            remaining = max(0.0, self._deadline - loop.time())
            done, still = await asyncio.wait(pending, timeout=remaining)
            self._collect(done)
            if still:
                for task in still:
                    task.cancel()
                await asyncio.gather(*still, return_exceptions=True)
                self.logger.warning(
                    "Photo review cancelled after %.0fs total timeout (%d request(s))",
                    self.total_timeout,
                    len(still),
                )
        self._collect([task for task in self._tasks if task.done()])
        return dict(self._reviews)


def merge_rich_text_segments(segments) -> tuple[str, bool]:
    """Merge richText segments into a single semantic text string.

    Text segments are concatenated as-is, except standalone @ mention
    segments (matching ^@\\S+$) are removed. Picture segments are
    replaced with <imgN> placeholders (N starts at 1).

    Returns the merged text and a flag telling whether any picture
    segment was present; the flag is the "has picture" signal reused
    by the unmatched-command fallback decision.
    """
    result_parts = []
    img_counter = 0
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        if "text" in seg:
            text = seg["text"]
            if isinstance(text, str) and re.match(r"^@\S+$", text):
                continue
            result_parts.append(str(text))
        elif "downloadCode" in seg:
            img_counter += 1
            result_parts.append(f"<img{img_counter}>")
    return "".join(result_parts), img_counter > 0


class BaseMessageHandler(ABC):
    """Abstract base class for message handlers."""

    @abstractmethod
    async def handle(
        self,
        message: ChatbotMessage,
        raw_data: dict,
        pipeline: "PipelineHandler",
    ) -> Optional[ReplyIntent]:
        """Handle incoming message. Return a ReplyIntent if the message is
        within this handler's responsibility, or None to stay silent."""
        pass

    def cancel_tasks(self) -> None:
        """Cancel this handler's interruptible in-flight tasks during shutdown.

        Handlers that own interruptible asyncio sub-tasks (e.g. media
        download) override this to cancel them. Non-interruptible work
        (e.g. file save / metadata commit) must NOT be registered and must
        always run to completion. Default: no-op.
        """
        return None


CommandAction = Callable[[ChatbotMessage, dict], Awaitable[str]]

# Guidance replies for text messages that match no command. The reply is
# composed from three orthogonal dimensions, each picked at random; all
# wording is fixed in code. See build_guide_reply().

# Dimension 1: empathy prefix; attached only when real text was sent.
UNMATCHED_PREFIX_TEXTS = (
    "不好意思，这句话我还没太听懂。",
    "哎呀，这条我有点没反应过来。",
    "抱歉，我暂时还没理解你的意思。",
    "嗯……这句话我还没学会。",
    "咦，这条消息我没看懂呢。",
    "抱歉呀，我没能明白你的意思。",
    "不好意思，你说的我有点跟不上。",
    "哎呀，这句话我暂时理解不了。",
    "抱歉抱歉，这条我还没搞懂。",
    "嗯？这个表达我还不太明白。",
    "咦，我好像没理解对意思。",
    "不好意思呀，这句话我需要再学学。",
)

# Dimension 2: list shell + per-capability wording. Capability wording is
# the only place carrying platform limits (files/videos stay single-chat);
# every variant is a verb phrase so it fits all shells.
GUIDE_BODY_TEMPLATES = (
    "我可以帮您：\n{caps}",
    "目前我支持这些操作：\n{caps}",
    "我能做的事情包括：\n{caps}",
    "您可以试试让我：\n{caps}",
    "我的本领有这些：\n{caps}",
    "我现在可以为您：\n{caps}",
    "我擅长的事情是：\n{caps}",
    "具体来说，我可以：\n{caps}",
    "这些事尽管交给我：\n{caps}",
    "我目前的能力有：\n{caps}",
    "让我来为您：\n{caps}",
    "您可以这样使用我：\n{caps}",
)

CAPABILITY_VARIANTS = (
    (
        "在群聊中接收您 @ 我发送的图片",
        "在群里接收您通过 @ 我发来的图片",
        "接收群成员 @ 我发送的图片",
        "处理群聊中 @ 我发来的图片",
        "在群聊里接收您 @ 我发出的图片",
        "接收您在群中 @ 我发送的图片",
    ),
    (
        "在单聊中接收您直接发送的图片",
        "接收您在私聊里直接发来的图片",
        "在一对一聊天中接收您发的图片",
        "接收单聊中无需 @ 直接发送的图片",
        "在单聊里接收您随手发来的图片",
        "接收您在单聊直接发给我的图片",
    ),
    (
        "在单聊中接收文件和视频",
        "接收您在私聊发来的文件与视频",
        "在单聊里处理文件和视频的接收",
        "接收您通过一对一聊天发送的文件、视频",
        "在单聊中接收您发来的视频和文件",
        "接收私聊场景下的文件和视频",
    ),
    (
        "把收到的内容自动保存到服务器",
        "将接收到的文件自动存档到服务器",
        "自动把您发来的内容妥善保存",
        "对收到的内容执行自动落盘保存",
        "把所有接收内容自动存到服务器",
        "将收到的内容自动保存归档",
    ),
)

# Dimension 3: ending prompt.
GUIDE_ENDING_TEXTS = (
    "请问您想做什么？",
    "您可以直接告诉我指令哦。",
    "需要我帮您做什么呢？",
    "请告诉我您的需求吧。",
    "想先试试哪一个？",
    "您想从哪一项开始呢？",
    "现在就可以发给我试试哦。",
    "有需要随时叫我。",
    "您希望我先帮您做什么？",
    "有什么我可以帮您的吗？",
    "随时把内容发给我就好。",
    "期待您的指令哦。",
)


def build_guide_reply(has_real_text: bool) -> str:
    """Compose one unmatched-command guidance reply.

    Prefix is included only when the sender actually sent text; empty
    content gets the capability list straight away.
    """
    prefix = random.choice(UNMATCHED_PREFIX_TEXTS) if has_real_text else ""
    lines = [f"• {random.choice(variants)}" for variants in CAPABILITY_VARIANTS]
    lines[-1] = f"{lines[-1]}。"
    body = random.choice(GUIDE_BODY_TEMPLATES).format(caps="\n".join(lines))
    return f"{prefix}{body}\n{random.choice(GUIDE_ENDING_TEXTS)}"


# Explicit replies for delivered-but-unsupported message types (single chat).
UNSUPPORTED_AUDIO_TEXT = "不好意思，语音消息我暂时还不支持接收哦。"
UNSUPPORTED_TYPE_TEXT = "不好意思，这种类型的消息我暂时还不支持接收。"

# Storage warmup notices, sent by the Dispatcher outside the intent model.
WAKING_STORAGE_TEXT = "正在唤醒存储服务，请稍候…"
STORAGE_UNAVAILABLE_TEXT = "存储服务暂时不可用，请稍后重试"


def _always_ready_probe() -> None:
    """Default storage probe: assumes storage is always ready (no-op)."""


class CommandHandler(BaseMessageHandler):
    """Resolve text commands with a matcher and dispatch them by command id."""

    def __init__(
        self,
        matcher: BaseCommandMatcher,
        dispatch_table: dict[str, CommandAction],
        logger: Optional[logging.Logger] = None,
    ):
        self._matcher = matcher
        self._dispatch_table = dispatch_table
        self.logger = logger or logging.getLogger(__name__)

    async def handle(
        self,
        message: ChatbotMessage,
        raw_data: dict,
        pipeline: "PipelineHandler",
    ) -> Optional[ReplyIntent]:
        """Match and execute command messages like '重建索引'."""
        msgtype = message.message_type or raw_data.get("msgtype")

        if msgtype == "text":
            content = ""
            if message.text and message.text.content:
                content = message.text.content
            elif "text" in raw_data and isinstance(raw_data["text"], dict):
                content = raw_data["text"].get("content", "")
        elif msgtype == "richText":
            segments = (raw_data.get("content") or {}).get("richText") or []
            content, _ = self._merge_rich_text(segments)
            self.logger.debug("RichText merged text: %s", content)
        else:
            return None

        normalized = normalize_command_text(content)

        # Empty or inquiry text skips the matcher entirely (no embedding
        # inference in semantic mode) and is simply treated as no match.
        if not normalized:
            self.logger.debug("Empty normalized text; skipping command matcher")
            command_id = None
        elif is_inquiry_text(normalized):
            self.logger.debug("Inquiry text; skipping command matcher: %s", normalized)
            command_id = None
        else:
            command_id = await self._matcher.match(normalized)

        if command_id is not None:
            self.logger.info("Command matched: %s", command_id)
            result_text = await self._dispatch_table[command_id](message, raw_data)
            return ReplyIntent(tier=ReplyTier.PRIMARY, text=result_text)

        self.logger.debug("Command unmatched; replying with guidance (text=%s)", normalized)
        return ReplyIntent(tier=ReplyTier.SECONDARY, text=build_guide_reply(bool(normalized)))

    @staticmethod
    def _merge_rich_text(segments) -> tuple[str, bool]:
        """Backward-compatible thin wrapper around merge_rich_text_segments."""
        return merge_rich_text_segments(segments)


class MediaFileHandler(BaseMessageHandler):
    """Handler for media and file messages (picture, video, file)."""

    SUPPORTED_MSG_TYPES = {"picture", "video", "file", "richText"}

    def __init__(
        self,
        output_dir: str,
        metadata_store,
        file_downloader,
        logger: Optional[logging.Logger] = None,
        reviewer: Optional["PhotoReviewer"] = None,
        review_merge_window: float = REVIEW_MERGE_WINDOW,
        review_timeout: float = REVIEW_TOTAL_TIMEOUT,
    ):
        self.output_dir = output_dir
        self.metadata_store = metadata_store
        self.file_downloader = file_downloader
        self.logger = logger or logging.getLogger(__name__)
        # Photo review is optional: None means "reply exactly like before".
        self.reviewer = reviewer
        self.review_merge_window = review_merge_window
        self.review_timeout = review_timeout
        # In-flight interruptible sub-tasks (download phase). Archive phase
        # (dedupe/save/commit/reply) runs inline and is never registered, so
        # cancel_tasks() cannot abort it.
        self._interruptible_tasks: set[asyncio.Task] = set()
        # Review tasks (batch requests and deferred follow-ups). They are
        # entertainment-only: shutdown cancels them instead of draining.
        self._review_tasks: set[asyncio.Task] = set()

    def disable_review(self) -> None:
        """Turn photo review off for this process (startup probe failed)."""
        if self.reviewer is not None:
            self.logger.info("Photo review disabled for this process.")
        self.reviewer = None

    def cancel_tasks(self) -> None:
        """Cancel download and review sub-tasks; archive work is untouched."""
        for task in list(self._interruptible_tasks):
            task.cancel()
        for task in list(self._review_tasks):
            task.cancel()

    async def handle(
        self,
        message: ChatbotMessage,
        raw_data: dict,
        pipeline: "PipelineHandler",
    ) -> Optional[ReplyIntent]:
        """Handle picture, video, file, and richText messages."""
        msgtype = message.message_type or raw_data.get("msgtype")
        if msgtype not in self.SUPPORTED_MSG_TYPES:
            return None

        content = raw_data.get("content") or {}

        if msgtype == "richText":
            return await self._handle_rich_text(message, raw_data, pipeline, content)

        download_code = None
        original_filename = None
        default_ext = ""

        if msgtype == "picture":
            if message.image_content and message.image_content.download_code:
                download_code = message.image_content.download_code
            else:
                download_code = content.get("downloadCode")
            original_filename = "picture.png"
            default_ext = ".png"
        elif msgtype == "video":
            download_code = content.get("downloadCode") or raw_data.get("downloadCode")
            original_filename = content.get("fileName") or "video.mp4"
            default_ext = ".mp4"
        elif msgtype == "file":
            download_code = content.get("downloadCode") or raw_data.get("downloadCode")
            original_filename = content.get("fileName") or "file.bin"
            default_ext = ".bin"

        if not download_code:
            self.logger.warning(f"No downloadCode found in {msgtype} message")
            return None

        result = await self._process_one_image(
            download_code, original_filename, default_ext, message, raw_data, msgtype
        )

        if result.status == "saved":
            reply = f"文件接收成功，已保存为: {result.detail}"
            if result.metadata:
                reply = f"{reply}\n{result.metadata}"
            batch = None
            if msgtype == "picture" and result.saved_path:
                batch = self._start_review_batch([(1, result.saved_path)])
            return await self._reply_with_reviews(reply, batch, message, pipeline)
        elif result.status == "cancelled":
            return ReplyIntent(tier=ReplyTier.PRIMARY, text=result.detail)
        else:
            return ReplyIntent(tier=ReplyTier.PRIMARY, text=result.detail)

    def _new_review_batch(self) -> Optional[_ReviewBatch]:
        """Create an empty batch, or None when review is disabled."""
        if self.reviewer is None:
            return None
        return _ReviewBatch(
            self.reviewer,
            [],
            total_timeout=self.review_timeout,
            logger=self.logger,
            registry=self._review_tasks,
        )

    def _start_review_batch(
        self, entries: list[tuple[int, str]]
    ) -> Optional[_ReviewBatch]:
        """Start review requests for saved photos, or None when disabled."""
        batch = self._new_review_batch()
        if batch is None or not entries:
            return None
        for index, path in entries:
            batch.add(index, path)
        batch.start()
        return batch

    async def _reply_with_reviews(
        self,
        reply_text: str,
        batch: Optional[_ReviewBatch],
        incoming_message: ChatbotMessage,
        pipeline: "PipelineHandler",
    ) -> ReplyIntent:
        """Merge reviews into the first reply, or defer them to a follow-up.

        The first reply is always returned as an intent so it keeps merging
        with other handlers' intents. When the window expires, a gated task is
        released only after the pipeline has sent that reply, which guarantees
        the review can never arrive first.
        """
        if batch is None:
            return ReplyIntent(tier=ReplyTier.PRIMARY, text=reply_text)

        reviews, pending = await batch.wait(self.review_merge_window)
        block = _format_reviews(reviews)
        if not pending:
            text = f"{reply_text}\n{block}" if block else reply_text
            return ReplyIntent(tier=ReplyTier.PRIMARY, text=text)

        gate = asyncio.Event()

        async def send_followup() -> None:
            try:
                await gate.wait()
                follow_text = _format_reviews(await batch.finish())
                if not follow_text:
                    return
                await pipeline.async_reply_text(
                    f"{REVIEW_PREFIX}\n{follow_text}", incoming_message
                )
            except asyncio.CancelledError:
                self.logger.info("Photo review follow-up cancelled by shutdown.")
                raise
            except Exception as exc:
                self.logger.warning(
                    "Photo review follow-up failed (%s): %s",
                    type(exc).__name__,
                    str(exc)[:200],
                )

        followup = asyncio.create_task(send_followup())
        self._review_tasks.add(followup)
        followup.add_done_callback(self._review_tasks.discard)

        def release() -> None:
            gate.set()

        return ReplyIntent(
            tier=ReplyTier.PRIMARY, text=reply_text, after_reply=release
        )

    async def _process_one_image(
        self,
        download_code: str,
        original_filename: str,
        default_ext: str,
        message: ChatbotMessage,
        raw_data: dict,
        msgtype: str,
    ) -> _ImageProcessResult:
        """Download, dedupe, and save a single media file.

        Returns a structured result; the caller decides how to reply.
        The download phase is interruptible via cancel_tasks(); the archive
        phase (dedupe/save/commit) is not.
        """
        # --- Interruptible phase: download ---
        # INFO marker before any download I/O so a cold-disk stall leaves a
        # trace of which media entered the pipeline. No code/URL/token here.
        self.logger.info(
            "Downloading file: type=%s, name=%s",
            msgtype,
            original_filename,
        )
        download_task = asyncio.create_task(self._download_phase(download_code))
        self._interruptible_tasks.add(download_task)
        try:
            download_result = await download_task
        except asyncio.CancelledError:
            self.logger.info(f"Download of {original_filename} interrupted by shutdown.")
            return _ImageProcessResult("cancelled", "服务正在关闭，下载任务已取消")
        except Exception as e:
            self.logger.error(f"Download failed for {original_filename}: {e}", exc_info=True)
            return _ImageProcessResult("failed", "文件接收处理失败，请稍后重试")
        finally:
            self._interruptible_tasks.discard(download_task)

        # --- Non-interruptible phase: archive (dedupe, save, commit) ---
        try:
            is_dup = await self.metadata_store.async_is_duplicate(download_result.sha256)
            if is_dup:
                self.logger.info(f"Duplicate file detected (sha256={download_result.sha256}), skipping save")
                if os.path.exists(download_result.temp_path):
                    try:
                        os.remove(download_result.temp_path)
                    except OSError:
                        pass
                return _ImageProcessResult("duplicate", "文件已存在，请勿重复发送")

            sender_nick = message.sender_nick or raw_data.get("senderNick")
            sender_id = message.sender_id or raw_data.get("senderId") or "unknown"
            sender_staff_id = message.sender_staff_id or raw_data.get("senderStaffId")

            saved_path = save_file(
                temp_path=download_result.temp_path,
                output_dir=self.output_dir,
                sender_staff_id=message.sender_staff_id,
                original_filename=original_filename,
                default_ext=default_ext,
            )

            await self.metadata_store.async_insert_record(
                sender_id=sender_id,
                sender_nick=sender_nick,
                original_filename=original_filename,
                saved_path=saved_path,
                sha256=download_result.sha256,
                file_size=download_result.file_size,
                media_type=msgtype,
                sender_staff_id=sender_staff_id,
            )

            saved_filename = os.path.basename(saved_path)
            self.logger.info(
                f"File saved: {saved_path} (sha256={download_result.sha256}, size={download_result.file_size})"
            )

            # Extract metadata for the reply (picture/video only); never
            # raises — failures yield None and the reply stays filename-only.
            metadata_line = extract_media_metadata(saved_path, msgtype)

            return _ImageProcessResult(
                "saved",
                saved_filename,
                metadata=metadata_line,
                saved_path=saved_path,
            )

        except Exception as e:
            self.logger.error(f"Failed to process media file ({original_filename}): {e}", exc_info=True)
            if os.path.exists(download_result.temp_path):
                try:
                    os.remove(download_result.temp_path)
                except OSError:
                    pass
            return _ImageProcessResult("failed", "文件接收处理失败，请稍后重试")

    async def _handle_rich_text(
        self,
        message: ChatbotMessage,
        raw_data: dict,
        pipeline: "PipelineHandler",
        content: dict,
    ) -> Optional[ReplyIntent]:
        """Handle richText messages: extract picture segments, save each, reply consolidated."""
        segments = content.get("richText") or []
        picture_segments = [seg for seg in segments if isinstance(seg, dict) and "downloadCode" in seg]

        if not picture_segments:
            return None

        results: List[_ImageProcessResult] = []
        batch = self._new_review_batch()
        for index, seg in enumerate(picture_segments, start=1):
            download_code = seg["downloadCode"]
            result = await self._process_one_image(
                download_code,
                original_filename=f"picture_{index}.png",
                default_ext=".png",
                message=message,
                raw_data=raw_data,
                msgtype="picture",
            )
            results.append(result)
            # Start each review as soon as its file is saved, so later
            # downloads overlap with earlier reviews.
            if batch is not None and result.status == "saved" and result.saved_path:
                batch.add(index, result.saved_path)
            if result.status == "cancelled":
                break

        reply_lines = []
        for result in results:
            if result.status == "saved":
                line = f"文件接收成功，已保存为: {result.detail}"
                if result.metadata:
                    line = f"{line}\n{result.metadata}"
                reply_lines.append(line)
            else:
                reply_lines.append(result.detail)

        if batch is not None:
            if batch:
                batch.start()
            else:
                batch = None
        return await self._reply_with_reviews(
            "\n".join(reply_lines), batch, message, pipeline
        )

    async def _download_phase(self, download_code: str):
        """Resolve download URL and stream the file to a temp path.

        Cancellable: begin_drain() cancels this sub-task via cancel_tasks();
        the downloader's BaseException handler removes the temp file.
        """
        download_url = await self.file_downloader.get_download_url(download_code)
        return await self.file_downloader.download_file_stream(download_url)


class PipelineHandler(dingtalk_stream.ChatbotHandler):
    """Message pipeline executing a chain of message handlers."""

    def __init__(
        self,
        handlers: Optional[List[BaseMessageHandler]] = None,
        logger: Optional[logging.Logger] = None,
        storage_probe: Optional[Callable[[], None]] = None,
        wake_warmup: Optional[Callable[[], Awaitable[None]]] = None,
        warmup_delay: float = 3.0,
    ):
        super().__init__()
        self.handlers: List[BaseMessageHandler] = handlers or []
        if logger:
            self.logger = logger
        else:
            self.logger = logging.getLogger(__name__)
        # Blocking storage warmup probe, run in a worker thread at dispatch
        # entry. Assembly binds the output-volume probe; tests may override.
        self.storage_probe = storage_probe or _always_ready_probe
        # Optional fire-and-forget model preload, started alongside the
        # cold-disk notice. The callback owns its own failure handling.
        self.wake_warmup = wake_warmup
        # Wake-notice timer. Production keeps the fixed 3.0s threshold; tests
        # shorten it through this constructor argument.
        self.warmup_delay = warmup_delay
        self._warmup_tasks: set[asyncio.Task] = set()
        # Shutdown drain state: in-flight background dispatch tasks. process()
        # creates the task that runs _dispatch, adds it here and unregisters it
        # from the completion callback.
        self._draining = False
        self._active_tasks: set[asyncio.Task] = set()

    async def async_reply_text(self, text: str, incoming_message: ChatbotMessage):
        """Send a text reply asynchronously in a worker thread, then log it.

        The DingTalk send runs before the local log write. The warmup and
        storage-unavailable notices are dispatched from inside
        ensure_storage_ready while the storage probe may still be waking a
        cold disk; a synchronous local log I/O must not delay the
        user-facing send, so logging happens after to_thread returns.

        Do NOT move the log call before the send. The send-before-log order
        is a contract recorded in the storage-warmup spec; no automated test
        asserts it, so this comment is the guard against silent regressions.
        """
        result = await asyncio.to_thread(self.reply_text, text, incoming_message)

        conversation_type = incoming_message.conversation_type
        if conversation_type == "2":
            target = f"group ({incoming_message.conversation_title or 'unknown group'})"
        else:
            target = f"private ({incoming_message.sender_nick or 'unknown'})"

        if result is None:
            self.logger.warning("Reply failed to %s: %s", target, text)
        else:
            self.logger.info("Replied to %s: %s", target, text)
        return result

    def is_draining(self) -> bool:
        """Return True after the shutdown intake gate has been closed."""
        return self._draining

    def begin_drain(self) -> None:
        """Close intake and ask every handler to cancel its interruptible tasks.

        Non-interruptible work (archive/commit/reply) is never touched; it
        runs to completion inside the still-tracked dispatch task.
        """
        self._draining = True
        for task in list(self._warmup_tasks):
            task.cancel()
        for handler in self.handlers:
            handler.cancel_tasks()
        self.logger.info("Intake gate closed; handlers notified to cancel interruptible tasks.")

    async def drain_active_tasks(self, timeout: float = 10.0) -> None:
        """Wait (bounded) for all in-flight background dispatch tasks to finish.

        begin_drain() already cancelled interruptible sub-tasks; each dispatch
        task then ends either via cancellation-reply or natural completion.
        """
        if not self._active_tasks:
            return
        _, pending = await asyncio.wait(self._active_tasks, timeout=timeout)
        if pending:
            self.logger.info(
                "Drain timeout after %.1fs; abandoning %d unfinished task(s) "
                "(they die with the process exit).",
                timeout,
                len(pending),
            )

    async def process(self, callback: CallbackMessage) -> Tuple[int, str]:
        """Acknowledge the callback at admission and dispatch processing.

        The platform's ack window is bounded, so the ack must not wait for the
        handler chain. Processing runs in a background task tracked by
        ``_active_tasks``, which keeps the shutdown drain semantics intact:
        ``begin_drain()`` still gates intake, and ``drain_active_tasks()``
        still waits for accepted work.
        """
        if self._draining:
            return AckMessage.STATUS_OK, "OK"

        task = asyncio.create_task(self._dispatch(callback))
        self._active_tasks.add(task)
        task.add_done_callback(self._on_dispatch_done)
        return AckMessage.STATUS_OK, "OK"

    def _on_dispatch_done(self, task: asyncio.Task) -> None:
        """Untrack a finished dispatch task and retrieve its exception.

        Fire-and-forget tasks lose the SDK's exception logging, so the
        exception must be retrieved here; otherwise it would surface only as
        "Task exception was never retrieved" at garbage collection.
        """
        self._active_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self.logger.error(
                "Background message processing failed (%s): %s",
                type(exc).__name__,
                str(exc)[:200],
                exc_info=exc,
            )

    def _log_received_message(self, message: ChatbotMessage, raw_data: dict) -> None:
        """Emit the INFO metadata summary (with text/richText body) and DEBUG
        credential/detail logs.

        The INFO summary now carries the readable body for text and richText
        so operators can follow a message at INFO without DEBUG. downloadCode,
        raw payload and callback headers stay at DEBUG. All logs run before
        any payload normalization (e.g. group @ prefix stripping).
        """
        sender = message.sender_nick or raw_data.get("senderNick") or "unknown"
        msg_type = message.message_type or raw_data.get("msgtype") or "unknown"
        content = raw_data.get("content") or {}

        conversation_type = message.conversation_type or raw_data.get("conversationType")
        if conversation_type == "2":
            group_title = message.conversation_title or raw_data.get("conversationTitle") or "unknown group"
            summary = f"Received group message from {sender} in {group_title}, type={msg_type}"
        elif conversation_type == "1":
            summary = f"Received private message from {sender}, type={msg_type}"
        else:
            summary = f"Received message from {sender}, type={msg_type}"

        if msg_type == "text":
            text_content = ""
            if message.text and message.text.content:
                text_content = message.text.content
            elif isinstance(raw_data.get("text"), dict):
                text_content = raw_data["text"].get("content", "")
            summary += f", content={text_content}"
        elif msg_type == "richText":
            segments = []
            if message.rich_text_content and message.rich_text_content.rich_text_list:
                segments = message.rich_text_content.rich_text_list
            elif isinstance(content.get("richText"), list):
                segments = content["richText"]
            text_count = sum(1 for item in segments if isinstance(item, dict) and "text" in item)
            picture_count = sum(1 for item in segments if isinstance(item, dict) and "downloadCode" in item)
            merged, _ = merge_rich_text_segments(segments)
            summary += (
                f", segments={len(segments)} ({text_count} text, {picture_count} picture)"
                f", content={merged}"
            )
        elif msg_type in ("file", "video"):
            filename = content.get("fileName")
            if filename:
                summary += f", filename={filename}"

        self.logger.info(summary)

        # DEBUG-only credential/detail logs: never promote these to INFO.
        if msg_type == "richText":
            segments = []
            if message.rich_text_content and message.rich_text_content.rich_text_list:
                segments = message.rich_text_content.rich_text_list
            elif isinstance(content.get("richText"), list):
                segments = content["richText"]
            total = len(segments)
            for index, item in enumerate(segments, start=1):
                if not isinstance(item, dict):
                    self.logger.debug("RichText segment[%d/%d] non-dict segment: %r", index, total, item)
                elif "downloadCode" in item:
                    self.logger.debug(
                        "RichText segment[%d/%d] picture: type=%s, downloadCode=%s",
                        index,
                        total,
                        item.get("type", "picture"),
                        item["downloadCode"],
                    )
                else:
                    self.logger.debug(
                        "RichText segment[%d/%d] other keys: %s",
                        index,
                        total,
                        sorted(item.keys()),
                    )
        elif msg_type == "picture":
            download_code = None
            if message.image_content and message.image_content.download_code:
                download_code = message.image_content.download_code
            else:
                download_code = content.get("downloadCode")
            self.logger.debug("Picture attachment: downloadCode=%s", download_code)
        elif msg_type in ("file", "video"):
            download_code = content.get("downloadCode") or raw_data.get("downloadCode")
            label = "File" if msg_type == "file" else "Video"
            filename = content.get("fileName")
            self.logger.debug(
                "%s attachment: fileName=%s, downloadCode=%s",
                label,
                filename,
                download_code,
            )

    async def _dispatch(self, callback: CallbackMessage) -> Tuple[int, str]:
        """Run the handler chain for one message."""
        raw_data = callback.data or {}
        incoming_message = ChatbotMessage.from_dict(raw_data)

        # Storage warmup must complete before the first log line: that log
        # write is synchronous stderr I/O and would otherwise stall the event
        # loop (and the warmup timer itself) on a sleeping disk. The warmup
        # notice and the unavailable notice are sent by the Dispatcher
        # directly, outside the intent model.
        #
        # Two orderings are easy to confuse here. This one is probe-before-log
        # (event-loop and timer latency). The other is send-before-log for each
        # user-facing notice (cold-disk log I/O must not delay the reply);
        # async_reply_text owns that order internally.
        def on_waking() -> Awaitable[None]:
            # Fire-and-forget: the wakeup notice must not wait for the preload.
            # The notice leaves through async_reply_text, which logs only after
            # the DingTalk send returns; keep that order.
            if self.wake_warmup is not None:
                task = asyncio.create_task(self.wake_warmup())
                self._warmup_tasks.add(task)
                task.add_done_callback(self._warmup_tasks.discard)
            return self.async_reply_text(WAKING_STORAGE_TEXT, incoming_message)

        try:
            await ensure_storage_ready(
                probe=self.storage_probe,
                on_waking=on_waking,
                delay=self.warmup_delay,
            )
        except Exception as e:
            self.logger.error(f"Storage warmup probe failed: {e}", exc_info=True)
            await self.async_reply_text(STORAGE_UNAVAILABLE_TEXT, incoming_message)
            return AckMessage.STATUS_OK, "OK"

        # INFO metadata summary first, then DEBUG typed content; both
        # precede any payload normalization (e.g. group @ prefix stripping)
        # so DEBUG output preserves the platform payload.
        self._log_received_message(incoming_message, raw_data)
        self.logger.debug(
            "Callback headers: %s",
            json.dumps(callback.headers.to_dict(), ensure_ascii=False, indent=2, default=str),
        )
        self.logger.debug("Message raw data: %s", json.dumps(raw_data, ensure_ascii=False, indent=2, default=str))

        intents: List[ReplyIntent] = []
        for handler in self.handlers:
            try:
                intent = await handler.handle(incoming_message, raw_data, self)
            except Exception as e:
                self.logger.error(
                    f"Error in handler {handler.__class__.__name__}: {e}",
                    exc_info=True,
                )
                continue
            if intent is not None:
                intents.append(intent)

        if intents:
            highest_tier = min(intent.tier for intent in intents)
            selected = [intent for intent in intents if intent.tier == highest_tier]
            merged = "\n".join(intent.text for intent in selected)
            await self.async_reply_text(merged, incoming_message)
            # Follow-ups (e.g. a deferred photo review) are released only
            # after the first reply has been delivered.
            for intent in selected:
                if intent.after_reply is None:
                    continue
                try:
                    intent.after_reply()
                except Exception as e:
                    self.logger.warning(
                        "Reply follow-up failed to start (%s): %s",
                        type(e).__name__,
                        str(e)[:200],
                    )
        else:
            conversation_type = incoming_message.conversation_type or raw_data.get("conversationType")
            if conversation_type == "1":
                msgtype = incoming_message.message_type or raw_data.get("msgtype")
                reply = UNSUPPORTED_AUDIO_TEXT if msgtype == "audio" else UNSUPPORTED_TYPE_TEXT
                await self.async_reply_text(reply, incoming_message)
            # Group messages with no intents stay silent (ACK only).

        return AckMessage.STATUS_OK, "OK"
