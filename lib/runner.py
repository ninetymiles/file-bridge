"""BotService: async lifecycle protocol for the DingTalk Stream client.

The :class:`BotService` exposes a stable ``async start()`` / ``async stop()``
protocol that encapsulates the SDK client, message pipeline and lifecycle
notifier. Callers may be CLI scripts (via :meth:`BotService.run_forever`) or
future ASGI lifespan hooks; this module does NOT depend on ASGI, Uvicorn or
FastAPI.
"""

import asyncio
import logging
import signal
from typing import Optional
import dingtalk_stream

from lib.lifecycle_notifier import LifecycleNotifier


class BotService:
    """Async lifecycle protocol wrapper for the DingTalk Stream client.

    The service exposes two idempotent public methods:

    - :meth:`start`: construct the runtime, send online notification, launch
      the SDK background task and register ``SIGINT``/``SIGTERM`` handlers.
    - :meth:`stop`: run the graceful shutdown sequence (``client.stop()`` ->
      ``runner_task.cancel()`` -> fire-and-forget offline notify -> close ws).

    Callers may also use :meth:`start_and_wait` for the convenience of waiting
    until a stop signal arrives, or :meth:`run_forever` for a synchronous
    entry point suitable for ``python -m app.main``.
    """

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
        self._is_started = False
        self._is_stopped = False

    async def start(self) -> None:
        """Idempotent start: register signal handlers, send online
        notification and launch the SDK background task.

        Calling :meth:`start` again after a successful start returns
        immediately without re-initialising.
        """
        if self._is_started:
            self.logger.debug("BotService.start() called again; already running.")
            return
        self._is_started = True
        self._is_stopped = False

        loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        self._is_shutting_down = False
        self._setup_signal_handlers(loop)

        # Send online notification if notifier is configured (blocking is fine
        # at startup; only offline notification needs to be fire-and-forget).
        if self.notifier:
            await self.notifier.send_online_notification()

        # Launch the SDK client in a background task so the event loop can
        # serve signal handlers and the stop event wait concurrently.
        self.logger.info("Starting DingTalk stream client runner...")
        self._runner_task = asyncio.create_task(self.client.start())

    async def stop(self) -> None:
        """Idempotent stop: run the graceful shutdown sequence.

        Order is significant (see
        ``openspec/changes/fix-graceful-shutdown-stuck-on-reconnect/design.md``):

        1. ``await client.stop()`` - set the SDK ``_stop_event`` and close the
           active websocket so the reconnect loop exits cleanly (not treated
           as a network exception triggering reconnect).
        2. ``runner_task.cancel()`` - cancel the SDK task in case it is
           blocked in a synchronous call; await with a 5s timeout.
        3. Fire-and-forget offline notification - failure must not block
           shutdown.
        4. Close websocket if still open (defensive; ``client.stop()`` should
           have closed it already).
        5. Brief ``await asyncio.sleep(0.1)`` to give the event loop a chance
           to schedule the fire-and-forget notification task before the loop
           tears down.

        Calling :meth:`stop` again after a successful stop returns
        immediately without re-running the shutdown sequence.
        """
        if self._is_stopped:
            self.logger.debug("BotService.stop() called again; already stopped.")
            return
        self._is_stopped = True

        self.logger.info("Executing graceful shutdown sequence...")

        # 1. Stop the SDK client first.
        try:
            await asyncio.wait_for(self.client.stop(), timeout=5.0)
        except asyncio.TimeoutError:
            self.logger.warning("Timeout stopping SDK client; proceeding with cancellation.")
        except Exception as e:
            self.logger.warning("Exception while stopping SDK client (ignored): %s", e)

        # 2. Cancel the runner task if still running.
        if self._runner_task and not self._runner_task.done():
            self._runner_task.cancel()
            try:
                await asyncio.wait_for(self._runner_task, timeout=5.0)
            except asyncio.TimeoutError:
                self.logger.warning("Timeout waiting for runner task to cancel.")
            except (asyncio.CancelledError, Exception):
                pass

        # 3. Fire-and-forget offline notification.
        if self.notifier:
            asyncio.create_task(self.notifier.send_offline_notification())

        # 4. Close websocket if still open (defensive).
        if hasattr(self.client, "websocket") and self.client.websocket is not None:
            try:
                await self.client.websocket.close()
            except Exception as e:
                self.logger.debug("Exception while closing websocket (ignored): %s", e)

        # 5. Give the event loop a moment to start the fire-and-forget
        #    notification task before asyncio.run() tears down the loop.
        await asyncio.sleep(0.1)

        self.logger.info("Graceful shutdown completed successfully.")

    async def start_and_wait(self) -> None:
        """Start the bot and block until a stop signal arrives, then stop.

        Convenience method used by :meth:`run_forever` for the CLI entry
        point. ASGI lifespan hooks typically call :meth:`start` and
        :meth:`stop` directly.
        """
        await self.start()
        try:
            await self._stop_event.wait()
        except asyncio.CancelledError:
            self.request_stop("CancelledError")
        await self.stop()

    def request_stop(self, signame: Optional[str] = None):
        """Signal the service to initiate graceful shutdown.

        On the first signal: synchronously set the SDK client's internal
        ``_stop_event`` so the SDK reconnect loop exits immediately (not
        waiting for the main loop's next await point), then set the
        service's own stop event to break out of the wait.

        On a subsequent signal (already shutting down): raise
        ``KeyboardInterrupt`` to give the user a force-exit escape hatch.
        """
        if self._is_shutting_down:
            sig_desc = f" ({signame})" if signame else ""
            self.logger.warning("Received second stop request%s, force exiting...", sig_desc)
            raise KeyboardInterrupt
        self._is_shutting_down = True
        sig_desc = f" ({signame})" if signame else ""
        self.logger.info("Received stop request%s, initiating graceful shutdown...", sig_desc)
        # Set the SDK's internal stop event immediately so its reconnect loop
        # (while not self._stop_event.is_set()) exits without waiting for the
        # main loop's await point. NOTE: `_stop_event` is a private SDK
        # attribute; review this access on SDK upgrade.
        sdk_stop_event = getattr(self.client, "_stop_event", None)
        if sdk_stop_event is not None and not sdk_stop_event.is_set():
            sdk_stop_event.set()
        if self._stop_event and not self._stop_event.is_set():
            self._stop_event.set()

    def _setup_signal_handlers(self, loop: asyncio.AbstractEventLoop):
        """Register signal handlers for SIGINT and SIGTERM."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda s=sig: self.request_stop(s.name))
            except (NotImplementedError, AttributeError):
                # Fallback for platforms/environments not supporting
                # loop.add_signal_handler (e.g. Windows).
                def make_sync_handler(s):
                    return lambda signum, frame: self.request_stop(s.name)
                try:
                    signal.signal(sig, make_sync_handler(sig))
                except Exception as e:
                    self.logger.warning("Could not register signal handler for %s: %s", sig, e)

    def run_forever(self) -> None:
        """Synchronous entry point that runs the async lifecycle.

        A first ``Ctrl-C`` triggers graceful shutdown inside
        :meth:`start_and_wait` and exits with status 0. A second ``Ctrl-C``
        (or any ``KeyboardInterrupt`` / ``SystemExit`` propagated from the
        async lifecycle) is re-raised so the process exits with non-zero
        status (130 by Unix convention for SIGINT).
        """
        try:
            asyncio.run(self.start_and_wait())
        except (KeyboardInterrupt, SystemExit):
            # Second Ctrl-C (force exit) or external signal: re-raise to
            # preserve non-zero exit status. A first Ctrl-C completes the
            # graceful shutdown sequence inside start_and_wait() and exits 0,
            # never reaching this branch.
            raise
