"""Message handlers and pipeline implementation for DingTalk stream bot."""

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
import dingtalk_stream
from dingtalk_stream import AckMessage, CallbackMessage, ChatbotMessage

from app.utils.file_storage import save_file


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


class CommandHandler(BaseMessageHandler):
    """Handler for command-based chatbot text messages."""

    def __init__(self, metadata_store, logger: Optional[logging.Logger] = None):
        self.metadata_store = metadata_store
        self.logger = logger or logging.getLogger(__name__)

    async def handle(
        self,
        message: ChatbotMessage,
        raw_data: dict,
        pipeline: "PipelineHandler",
    ) -> bool:
        """Match and execute command messages like '重建索引'."""
        if message.message_type != "text" and raw_data.get("msgtype") != "text":
            return False

        content = ""
        if message.text and message.text.content:
            content = message.text.content
        elif "text" in raw_data and isinstance(raw_data["text"], dict):
            content = raw_data["text"].get("content", "")

        content = content.strip()

        # Check for '重建索引' command
        if "重建索引" in content:
            self.logger.info("Command matched: 重建索引")
            cleaned_count, remaining_count = await self.metadata_store.async_rebuild_index()
            response_text = f"索引重建完成，清理元数据 {cleaned_count} 条，现有有效索引 {remaining_count} 条。"
            await pipeline.async_reply_text(response_text, message)
            return True

        return False


class MediaFileHandler(BaseMessageHandler):
    """Handler for media and file messages (picture, video, file)."""

    SUPPORTED_MSG_TYPES = {"picture", "video", "file"}

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
        """Handle picture, video, and file messages."""
        msgtype = message.message_type or raw_data.get("msgtype")
        if msgtype not in self.SUPPORTED_MSG_TYPES:
            return False

        content = raw_data.get("content") or {}
        download_code = None
        original_filename = None
        default_ext = ""

        if msgtype == "picture":
            if message.image_content and message.image_content.download_code:
                download_code = message.image_content.download_code
            else:
                download_code = content.get("downloadCode")
            original_filename = content.get("fileName") or "picture.png"
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

        # Shutdown checkpoint: abandon before starting any download work.
        if pipeline.is_draining():
            self.logger.info(f"Shutdown in progress; abandoning {msgtype} message before download.")
            return True

        # --- Interruptible phase: download ---
        # Run as a registered sub-task so begin_drain() can cancel only the
        # download and leave the archive phase (dedupe/save/commit/reply)
        # untouched. download_file_stream's BaseException handler cleans the
        # temp file on cancellation.
        download_task = asyncio.create_task(
            self._download_phase(download_code)
        )
        self._interruptible_tasks.add(download_task)
        try:
            download_result = await download_task
        except asyncio.CancelledError:
            self.logger.info(f"Download of {msgtype} interrupted by shutdown.")
            await pipeline.async_reply_text("服务正在关闭，下载任务已取消", message)
            return True
        finally:
            self._interruptible_tasks.discard(download_task)

        # --- Non-interruptible phase: archive (dedupe, save, commit, reply) ---
        try:
            # Check for duplicate
            is_dup = await self.metadata_store.async_is_duplicate(download_result.sha256)
            if is_dup:
                self.logger.info(f"Duplicate file detected (sha256={download_result.sha256}), skipping save")
                if os.path.exists(download_result.temp_path):
                    try:
                        os.remove(download_result.temp_path)
                    except OSError:
                        pass
                await pipeline.async_reply_text("文件已存在，请勿重复发送", message)
                return True

            # Save file to destination directory
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

            self.logger.info(
                f"File saved: {saved_path} (sha256={download_result.sha256}, size={download_result.file_size})"
            )

            saved_filename = os.path.basename(saved_path)
            await pipeline.async_reply_text(f"文件接收成功，已保存为: {saved_filename}", message)
            return True

        except Exception as e:
            self.logger.error(f"Failed to process media message ({msgtype}): {e}", exc_info=True)
            if os.path.exists(download_result.temp_path):
                try:
                    os.remove(download_result.temp_path)
                except OSError:
                    pass
            await pipeline.async_reply_text("文件接收处理失败，请稍后重试", message)
            return True

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
