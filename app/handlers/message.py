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
from typing import List, Optional, Tuple
import dingtalk_stream
from dingtalk_stream import AckMessage, CallbackMessage, ChatbotMessage

from app.services.command_matching import BaseCommandMatcher, normalize_command_text
from app.services.media_metadata import extract_media_metadata
from app.utils.file_storage import save_file


@dataclass
class _ImageProcessResult:
    """Result of processing a single image (download + dedupe + save)."""

    status: str  # "saved" | "duplicate" | "failed" | "cancelled"
    detail: str  # saved filename for "saved", reply message for others
    metadata: Optional[str] = None  # formatted metadata summary line, or None


class BaseMessageHandler(ABC):
    """Abstract base class for message handlers."""

    @abstractmethod
    async def handle(
        self,
        message: ChatbotMessage,
        raw_data: dict,
        pipeline: "PipelineHandler",
    ) -> bool:
        """Handle incoming message. Return True if handled (halting pipeline), False otherwise."""
        pass

    def cancel_tasks(self) -> None:
        """Cancel this handler's interruptible in-flight tasks during shutdown.

        Handlers that own interruptible asyncio sub-tasks (e.g. media
        download) override this to cancel them. Non-interruptible work
        (e.g. file save / metadata commit) must NOT be registered and must
        always run to completion. Default: no-op.
        """
        return None


CommandAction = Callable[[ChatbotMessage, dict, "PipelineHandler"], Awaitable[None]]

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
    ) -> bool:
        """Match and execute command messages like '重建索引'."""
        msgtype = message.message_type or raw_data.get("msgtype")

        has_picture = False
        if msgtype == "text":
            content = ""
            if message.text and message.text.content:
                content = message.text.content
            elif "text" in raw_data and isinstance(raw_data["text"], dict):
                content = raw_data["text"].get("content", "")
        elif msgtype == "richText":
            segments = (raw_data.get("content") or {}).get("richText") or []
            content, has_picture = self._merge_rich_text(segments)
            self.logger.debug("RichText merged text: %s", content)
        else:
            return False

        normalized = normalize_command_text(content)

        # Empty text skips the matcher entirely (no embedding inference in
        # semantic mode) and is simply treated as no match.
        if normalized:
            command_id = await self._matcher.match(normalized)
        else:
            self.logger.debug(
                "Empty normalized text; skipping command matcher (has_picture=%s)",
                has_picture,
            )
            command_id = None

        if command_id is not None:
            self.logger.info("Command matched: %s", command_id)
            await self._dispatch_table[command_id](message, raw_data, pipeline)
        elif not has_picture:
            # No command and no picture segment: guide the sender on how the
            # bot can be used.
            self.logger.debug("Command unmatched; replying with guidance (text=%s)", normalized)
            await pipeline.async_reply_text(build_guide_reply(bool(normalized)), message)
        else:
            # Messages carrying pictures stay silent here; their save result
            # is reported by the media flow instead.
            self.logger.debug("Command unmatched; media message stays silent (text=%s)", normalized)

        # Commands do not halt the chain so a richText message can both run a
        # command and let MediaFileHandler archive its pictures.
        return False

    @staticmethod
    def _merge_rich_text(segments) -> tuple[str, bool]:
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


class MediaFileHandler(BaseMessageHandler):
    """Handler for media and file messages (picture, video, file)."""

    SUPPORTED_MSG_TYPES = {"picture", "video", "file", "richText"}

    def __init__(
        self,
        output_dir: str,
        metadata_store,
        file_downloader,
        logger: Optional[logging.Logger] = None,
    ):
        self.output_dir = output_dir
        self.metadata_store = metadata_store
        self.file_downloader = file_downloader
        self.logger = logger or logging.getLogger(__name__)
        # In-flight interruptible sub-tasks (download phase). Archive phase
        # (dedupe/save/commit/reply) runs inline and is never registered, so
        # cancel_tasks() cannot abort it.
        self._interruptible_tasks: set[asyncio.Task] = set()

    def cancel_tasks(self) -> None:
        """Cancel all in-flight download sub-tasks; archive work is untouched."""
        for task in list(self._interruptible_tasks):
            task.cancel()

    async def handle(
        self,
        message: ChatbotMessage,
        raw_data: dict,
        pipeline: "PipelineHandler",
    ) -> bool:
        """Handle picture, video, file, and richText messages."""
        msgtype = message.message_type or raw_data.get("msgtype")
        if msgtype not in self.SUPPORTED_MSG_TYPES:
            # Only single chat can deliver such frames (groups never get
            # file/video/audio): tell the sender clearly instead of silence.
            conversation_type = message.conversation_type or raw_data.get("conversationType")
            if conversation_type == "1":
                reply = UNSUPPORTED_AUDIO_TEXT if msgtype == "audio" else UNSUPPORTED_TYPE_TEXT
                await pipeline.async_reply_text(reply, message)
            return False

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
            return False

        result = await self._process_one_image(
            download_code, original_filename, default_ext, message, raw_data, msgtype
        )

        if result.status == "saved":
            reply = f"文件接收成功，已保存为: {result.detail}"
            if result.metadata:
                reply = f"{reply}\n{result.metadata}"
            await pipeline.async_reply_text(reply, message)
        elif result.status == "cancelled":
            await pipeline.async_reply_text(result.detail, message)
        else:
            await pipeline.async_reply_text(result.detail, message)
        return False

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
            sender_id = message.sender_id or raw_data.get("senderId") or message.sender_staff_id or "unknown"
            sender = sender_nick or sender_id

            saved_path = save_file(
                temp_path=download_result.temp_path,
                output_dir=self.output_dir,
                sender=sender,
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
            )

            saved_filename = os.path.basename(saved_path)
            self.logger.info(
                f"File saved: {saved_path} (sha256={download_result.sha256}, size={download_result.file_size})"
            )

            # Extract metadata for the reply (picture/video only); never
            # raises — failures yield None and the reply stays filename-only.
            metadata_line = extract_media_metadata(saved_path, msgtype)

            return _ImageProcessResult("saved", saved_filename, metadata=metadata_line)

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
    ) -> bool:
        """Handle richText messages: extract picture segments, save each, reply consolidated."""
        segments = content.get("richText") or []
        picture_segments = [seg for seg in segments if isinstance(seg, dict) and "downloadCode" in seg]

        if not picture_segments:
            return False

        results: List[_ImageProcessResult] = []
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

        await pipeline.async_reply_text("\n".join(reply_lines), message)
        return False

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
    ):
        super().__init__()
        self.handlers: List[BaseMessageHandler] = handlers or []
        if logger:
            self.logger = logger
        else:
            self.logger = logging.getLogger(__name__)
        # Shutdown drain state: in-flight SDK message tasks (set of asyncio.Task).
        # Each message runs in its own SDK-created task; process() registers it.
        self._draining = False
        self._active_tasks: set[asyncio.Task] = set()

    async def async_reply_text(self, text: str, incoming_message: ChatbotMessage):
        """Send a text reply asynchronously in a worker thread."""
        return await asyncio.to_thread(self.reply_text, text, incoming_message)

    def is_draining(self) -> bool:
        """Return True after the shutdown intake gate has been closed."""
        return self._draining

    def begin_drain(self) -> None:
        """Close intake and ask every handler to cancel its interruptible tasks.

        Non-interruptible work (archive/commit/reply) is never touched; it
        runs to completion inside the still-registered SDK task.
        """
        self._draining = True
        for handler in self.handlers:
            handler.cancel_tasks()
        self.logger.info("Intake gate closed; handlers notified to cancel interruptible tasks.")

    async def drain_active_tasks(self, timeout: float = 10.0) -> None:
        """Wait (bounded) for all in-flight SDK message tasks to finish.

        begin_drain() already cancelled interruptible sub-tasks; each SDK
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
        """Process callback message through the pipeline.

        Shutdown-aware wrapper: after begin_drain() the intake gate acks
        without processing; every in-flight SDK task registers itself and
        deregisters in finally, whatever way it ends.
        """
        if self._draining:
            return AckMessage.STATUS_OK, "OK"

        task = asyncio.current_task()
        self._active_tasks.add(task)
        try:
            return await self._dispatch(callback)
        finally:
            self._active_tasks.discard(task)

    def _log_received_message(self, message: ChatbotMessage, raw_data: dict) -> None:
        """Emit the INFO metadata summary and DEBUG typed content logs.

        INFO must stay free of message bodies, download codes and URLs;
        DEBUG carries the full typed content. All logs run before any
        payload normalization (e.g. group @ prefix stripping).
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

        if msg_type == "richText":
            segments = []
            if message.rich_text_content and message.rich_text_content.rich_text_list:
                segments = message.rich_text_content.rich_text_list
            elif isinstance(content.get("richText"), list):
                segments = content["richText"]
            text_count = sum(1 for item in segments if isinstance(item, dict) and "text" in item)
            picture_count = sum(1 for item in segments if isinstance(item, dict) and "downloadCode" in item)
            summary += f", segments={len(segments)} ({text_count} text, {picture_count} picture)"
        elif msg_type in ("file", "video"):
            filename = content.get("fileName")
            if filename:
                summary += f", filename={filename}"

        self.logger.info(summary)

        if msg_type == "text":
            text_content = ""
            if message.text and message.text.content:
                text_content = message.text.content
            elif isinstance(raw_data.get("text"), dict):
                text_content = raw_data["text"].get("content", "")
            self.logger.debug("Text content: %s", text_content)
        elif msg_type == "richText":
            segments = []
            if message.rich_text_content and message.rich_text_content.rich_text_list:
                segments = message.rich_text_content.rich_text_list
            elif isinstance(content.get("richText"), list):
                segments = content["richText"]
            total = len(segments)
            for index, item in enumerate(segments, start=1):
                if not isinstance(item, dict):
                    self.logger.debug("RichText segment[%d/%d] non-dict segment: %r", index, total, item)
                elif "text" in item:
                    self.logger.debug("RichText segment[%d/%d] text: %s", index, total, item["text"])
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

        # INFO metadata summary first, then DEBUG typed content; both
        # precede any payload normalization (e.g. group @ prefix stripping)
        # so DEBUG output preserves the platform payload.
        self._log_received_message(incoming_message, raw_data)
        self.logger.debug(
            "Callback headers: %s",
            json.dumps(callback.headers.to_dict(), ensure_ascii=False, indent=2, default=str),
        )
        self.logger.debug("Message raw data: %s", json.dumps(raw_data, ensure_ascii=False, indent=2, default=str))

        for handler in self.handlers:
            try:
                handled = await handler.handle(incoming_message, raw_data, self)
                if handled:
                    self.logger.debug(f"Message handled by {handler.__class__.__name__}")
                    return AckMessage.STATUS_OK, "OK"
            except Exception as e:
                self.logger.error(
                    f"Error in handler {handler.__class__.__name__}: {e}",
                    exc_info=True,
                )
                return AckMessage.STATUS_OK, "OK"

        return AckMessage.STATUS_OK, "OK"
