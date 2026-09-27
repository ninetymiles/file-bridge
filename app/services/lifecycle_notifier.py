"""Lifecycle notification module for sending online and offline status messages."""

import asyncio
import logging
from typing import List, Optional, Tuple
import dingtalk_stream


class LifecycleNotifier:
    """Manages active online and offline notifications to DingTalk chats."""

    # Target kinds used in log messages and target routing.
    TARGET_KIND_GROUP = "group"
    TARGET_KIND_STAFF = "staff"

    def __init__(
        self,
        dingtalk_client: Optional[dingtalk_stream.DingTalkStreamClient] = None,
        notify_conversation_id: Optional[str] = None,
        notify_staff_id: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        timeout: float = 5.0,
    ):
        self.dingtalk_client = dingtalk_client
        self.notify_conversation_id = notify_conversation_id
        self.notify_staff_id = notify_staff_id
        self.logger = logger or logging.getLogger("file-bridge.lifecycle")
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        """Check if any notification target is configured."""
        return bool(self.notify_conversation_id or self.notify_staff_id)

    def _build_targets(self) -> List[Tuple[str, str]]:
        """Return configured targets as (kind, target_id) pairs.

        Order is fixed: group chat first, single chat second.
        """
        targets = []
        if self.notify_conversation_id:
            targets.append((self.TARGET_KIND_GROUP, self.notify_conversation_id))
        if self.notify_staff_id:
            targets.append((self.TARGET_KIND_STAFF, self.notify_staff_id))
        return targets

    def _send_to_target(
        self,
        handler: "dingtalk_stream.ChatbotHandler",
        kind: str,
        target_id: str,
        title: str,
        content: str,
    ) -> bool:
        """Send one notification to a single target with isolated failure handling.

        Both raised exceptions and SDK-silent failures (empty card instance id)
        are treated as failure; callers can keep sending to remaining targets.
        """
        try:
            if kind == self.TARGET_KIND_GROUP:
                message = dingtalk_stream.reply_specified_group_chat(target_id)
            else:
                message = dingtalk_stream.reply_specified_single_chat(target_id)

            card_instance = handler.reply_markdown_card(content, message, title=title)
            card_instance_id = getattr(card_instance, "card_instance_id", "")
            if not card_instance_id:
                self.logger.warning(
                    "Lifecycle notification delivery failed for %s target (%s): "
                    "empty card instance id returned by SDK",
                    kind,
                    title,
                )
                return False
            self.logger.info(
                "Lifecycle notification sent to %s target successfully: %s", kind, title
            )
            return True
        except Exception as e:
            self.logger.warning(
                "Failed to send lifecycle notification to %s target (%s): %s",
                kind,
                title,
                e,
            )
            return False

    def _send_sync(self, title: str, content: str) -> bool:
        """Synchronously send markdown notification to every configured target."""
        if not self.is_configured:
            self.logger.debug("No notification target configured; skipping lifecycle notification.")
            return True

        if not self.dingtalk_client:
            self.logger.warning("DingTalk client is not provided; skipping lifecycle notification.")
            return False

        handler = dingtalk_stream.ChatbotHandler()
        handler.dingtalk_client = self.dingtalk_client

        all_succeeded = True
        for kind, target_id in self._build_targets():
            if not self._send_to_target(handler, kind, target_id, title, content):
                all_succeeded = False
        return all_succeeded

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
