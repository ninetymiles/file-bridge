"""Lifecycle notification module for sending online and offline status messages."""

import asyncio
import logging
from typing import Optional
import dingtalk_stream


class LifecycleNotifier:
    """Manages active online and offline notifications to DingTalk chats."""

    def __init__(
        self,
        dingtalk_client: Optional[dingtalk_stream.DingTalkStreamClient] = None,
        notify_conversation_id: Optional[str] = None,
        notify_user_id: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        timeout: float = 5.0,
    ):
        self.dingtalk_client = dingtalk_client
        self.notify_conversation_id = notify_conversation_id
        self.notify_user_id = notify_user_id
        self.logger = logger or logging.getLogger("file-bridge.lifecycle")
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        """Check if any notification target is configured."""
        return bool(self.notify_conversation_id or self.notify_user_id)

    def _send_sync(self, title: str, content: str) -> bool:
        """Synchronously send markdown notification to the configured target."""
        if not self.is_configured:
            self.logger.debug("No notification target configured; skipping lifecycle notification.")
            return True

        if not self.dingtalk_client:
            self.logger.warning("DingTalk client is not provided; skipping lifecycle notification.")
            return False

        try:
            if self.notify_conversation_id:
                msg = dingtalk_stream.reply_specified_group_chat(self.notify_conversation_id)
            else:
                msg = dingtalk_stream.reply_specified_single_chat(self.notify_user_id)

            handler = dingtalk_stream.ChatbotHandler()
            handler.dingtalk_client = self.dingtalk_client
            handler.reply_markdown_card(content, msg, title=title)
            self.logger.info("Lifecycle notification sent successfully: %s", title)
            return True
        except Exception as e:
            self.logger.warning("Failed to send lifecycle notification (%s): %s", title, e)
            return False

    async def send_notification(self, title: str, content: str) -> bool:
        """Send notification asynchronously in a thread pool with timeout protection."""
        if not self.is_configured:
            self.logger.debug("No notification target configured; skipping lifecycle notification.")
            return True

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._send_sync, title, content),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            self.logger.warning("Timeout (%ss) sending lifecycle notification: %s", self.timeout, title)
            return False
        except Exception as e:
            self.logger.warning("Unexpected error sending lifecycle notification (%s): %s", title, e)
            return False

    async def send_online_notification(self) -> bool:
        """Send service online notification."""
        title = "🤖 File Bridge 机器人已上线"
        content = "### 🤖 File Bridge 机器人已上线\n服务已就绪，正在监听消息。"
        return await self.send_notification(title, content)

    async def send_offline_notification(self) -> bool:
        """Send service offline notification."""
        title = "🛑 File Bridge 机器人已离线"
        content = "### 🛑 File Bridge 机器人已离线\n服务已接收停机信号并完成清理。"
        return await self.send_notification(title, content)
