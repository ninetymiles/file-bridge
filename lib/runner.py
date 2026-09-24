"""Lifecycle runner for DingTalk Stream client managing graceful shutdown and signals."""

import asyncio
import logging
import signal
from typing import Optional
import dingtalk_stream

from lib.lifecycle_notifier import LifecycleNotifier


class BotRunner:
    """Manages the execution, signal handling, and graceful shutdown of a DingTalk Stream client."""

    def __init__(
        self,
        client: dingtalk_stream.DingTalkStreamClient,
        notifier: Optional[LifecycleNotifier] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.client = client
        self.notifier = notifier
        self.logger = logger or logging.getLogger("file-bridge.runner")
        self._stop_event: Optional[asyncio.Event] = None
        self._runner_task: Optional[asyncio.Task] = None
        self._is_shutting_down = False

    def request_stop(self, signame: Optional[str] = None):
        """Signal the runner to initiate graceful shutdown."""
        if self._is_shutting_down:
            return
        self._is_shutting_down = True
        sig_desc = f" ({signame})" if signame else ""
        self.logger.info("Received stop request%s, initiating graceful shutdown...", sig_desc)
        if self._stop_event and not self._stop_event.is_set():
            self._stop_event.set()

    def _setup_signal_handlers(self, loop: asyncio.AbstractEventLoop):
        """Register signal handlers for SIGINT and SIGTERM."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda s=sig: self.request_stop(s.name))
            except (NotImplementedError, AttributeError):
                # Fallback for platforms/environments not supporting loop.add_signal_handler (e.g. Windows)
                def make_sync_handler(s):
                    return lambda signum, frame: self.request_stop(s.name)
                try:
                    signal.signal(sig, make_sync_handler(sig))
                except Exception as e:
                    self.logger.warning("Could not register signal handler for %s: %s", sig, e)

    async def run(self):
        """Asynchronously run the stream client with lifecycle notifications and signal handling."""
        loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        self._is_shutting_down = False
        self._setup_signal_handlers(loop)

        # 1. Send online notification if notifier is configured
        if self.notifier:
            await self.notifier.send_online_notification()

        # 2. Launch client.start in a background task
        self.logger.info("Starting DingTalk stream client runner...")
        self._runner_task = asyncio.create_task(self.client.start())

        # 3. Wait until stop signal is received
        try:
            await self._stop_event.wait()
        except asyncio.CancelledError:
            self.request_stop("CancelledError")

        # 4. Graceful shutdown sequence
        self.logger.info("Executing graceful shutdown sequence...")

        # 4.1 Send offline notification before tearing down connections
        if self.notifier:
            await self.notifier.send_offline_notification()

        # 4.2 Close the active websocket connection if available
        if hasattr(self.client, "websocket") and self.client.websocket is not None:
            try:
                await self.client.websocket.close()
            except Exception as e:
                self.logger.debug("Exception while closing websocket (ignored): %s", e)

        # 4.3 Cancel the stream runner task
        if self._runner_task and not self._runner_task.done():
            self._runner_task.cancel()
            try:
                await self._runner_task
            except (asyncio.CancelledError, Exception):
                pass

        self.logger.info("Graceful shutdown completed successfully.")

    def start_forever(self):
        """Synchronous entry point that runs the async lifecycle."""
        try:
            asyncio.run(self.run())
        except (KeyboardInterrupt, SystemExit):
            pass
