"""Message handlers and pipeline implementation for DingTalk stream bot."""

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
import dingtalk_stream
from dingtalk_stream import AckMessage, CallbackMessage, ChatbotMessage

from lib.file_storage import save_file


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

        download_result = None
        try:
            self.logger.info(f"Processing {msgtype} message: filename={original_filename}")
            download_url = await self.file_downloader.get_download_url(download_code)
            download_result = await self.file_downloader.download_file_stream(download_url)

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
            if download_result and os.path.exists(download_result.temp_path):
                try:
                    os.remove(download_result.temp_path)
                except OSError:
                    pass
            await pipeline.async_reply_text("文件接收处理失败，请稍后重试", message)
            return True


class CalcBotFallbackHandler(BaseMessageHandler):
    """Fallback handler preserving calculation functionality."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)

    async def handle(
        self,
        message: ChatbotMessage,
        raw_data: dict,
        pipeline: "PipelineHandler",
    ) -> bool:
        if message.message_type != "text" and raw_data.get("msgtype") != "text":
            return False

        content = ""
        if message.text and message.text.content:
            content = message.text.content
        elif "text" in raw_data and isinstance(raw_data["text"], dict):
            content = raw_data["text"].get("content", "")

        expression = content.strip()
        if "+" not in expression:
            return False

        try:
            operands = [float(part.strip()) for part in expression.split("+")]
            if len(operands) < 2:
                return False
            result = sum(operands)
            if result.is_integer():
                result = int(result)
        except Exception:
            return False

        self.logger.info(f"{expression} = {result}")
        response = f"Q: {expression}\nA: {result}"
        await pipeline.async_reply_text(response, message)
        return True


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

    def add_handler(self, handler: BaseMessageHandler) -> "PipelineHandler":
        """Append a handler to the pipeline."""
        self.handlers.append(handler)
        return self

    async def async_reply_text(self, text: str, incoming_message: ChatbotMessage):
        """Send a text reply asynchronously in a worker thread."""
        return await asyncio.to_thread(self.reply_text, text, incoming_message)

    async def process(self, callback: CallbackMessage) -> Tuple[int, str]:
        """Process callback message through the pipeline."""
        raw_data = callback.data or {}
        incoming_message = ChatbotMessage.from_dict(raw_data)

        sender = incoming_message.sender_nick or raw_data.get("senderNick") or "unknown"
        msg_type = incoming_message.message_type or raw_data.get("msgtype") or "unknown"
        self.logger.info(f"Received message from {sender}, type={msg_type}")
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
