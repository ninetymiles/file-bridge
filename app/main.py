# !/usr/bin/env python

import argparse
import logging
import os
from functools import partial
from typing import List, Optional
import dingtalk_stream
import dotenv

from app.services.command_matching import (
    REBUILD_INDEX,
    build_command_matcher,
    parse_enabled,
)
from app.services.metadata_store import MetadataStore
from app.services.file_downloader import FileDownloader
from app.services.lifecycle_notifier import LifecycleNotifier
from app.core.runner import BotService
from app.handlers import (
    PipelineHandler,
    CommandHandler,
    MediaFileHandler,
)
from app.utils.file_storage import write_activity_file

DEFAULT_OUTPUT_DIR = "./output"
DEFAULT_LOG_LEVEL = "INFO"

LOG_FORMAT = '%(asctime)s %(name)-8s %(levelname)-8s %(message)s [%(filename)s:%(lineno)d]'

LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class _DingTalkStreamLogFilter(logging.Filter):
    """Reshape dingtalk_stream connection logs to concise INFO conclusions.

    The SDK routes its logs through the application logger (name=file-bridge,
    filename=stream.py). This filter rewrites verbose connection records into
    short conclusion lines and downgrades the open-connection URL line to
    DEBUG, so INFO stays focused on lifecycle outcomes without leaking
    endpoint tickets or disconnect JSON payloads.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "file-bridge" or record.filename != "stream.py":
            return True

        msg = record.getMessage()
        if msg.startswith("received disconnect topic=disconnect"):
            record.msg = "DingTalk stream disconnected: received disconnect message"
            record.args = ()
        elif msg.startswith("endpoint is "):
            record.msg = "DingTalk stream connected."
            record.args = ()
        elif msg.startswith("open connection, url="):
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
        return True


def get_app_version() -> str:
    """Return the running version from the APP_VERSION env var (default "dev").

    The version is injected by the CI build from the git tag via a Dockerfile
    ARG/ENV pair; local runs and builds without the build arg fall back to
    "dev". ``or`` is used (instead of a default value on ``getenv``) so an
    empty APP_VERSION also resolves to "dev" (branch pushes can yield an
    empty meta.outputs.version).
    """
    return os.getenv("APP_VERSION") or "dev"


def resolve_log_level(raw: Optional[str]) -> int:
    """Map a case-insensitive level name to a numeric logging level.

    Empty or unrecognized values fall back to logging.INFO.
    """
    if raw:
        level = LOG_LEVELS.get(raw.strip().upper())
        if level is not None:
            return level
    return logging.INFO


def setup_logger(log_level: Optional[str] = DEFAULT_LOG_LEVEL) -> logging.Logger:
    """Configure root logging and return the application logger.

    The root logger stays at INFO so third-party DEBUG frames stay quiet.
    The file-bridge logger follows LOG_LEVEL and emits through the root
    handler via propagation: no private handler is attached, avoiding
    duplicate output.

    A handler-level filter reshapes dingtalk_stream connection records
    (name=file-bridge, filename=stream.py) into concise INFO conclusions
    and downgrades the open-connection URL line to DEBUG. The httpx logger
    is pinned to WARNING so per-request INFO lines (which carry signed OSS
    URLs) never appear at the default level.
    """
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(_DingTalkStreamLogFilter())
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logger = logging.getLogger("file-bridge")
    logger.setLevel(resolve_log_level(log_level))
    if log_level is not None and log_level.strip().upper() not in LOG_LEVELS:
        logger.warning("Invalid LOG_LEVEL %r; falling back to INFO.", log_level)
    return logger


def parse_config(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments and environment variables into runtime options.

    Priority: command-line arguments > environment variables (incl. .env).
    Environment fallback happens solely via add_argument defaults.
    """
    parser = argparse.ArgumentParser(description="DingTalk Stream Bot Configuration")
    parser.add_argument(
        '--client-id',
        dest='client_id',
        default=os.getenv('CLIENT_ID'),
        help='app_key or suite_key from https://open-dev.dingtalk.com'
    )
    parser.add_argument(
        '--client-secret',
        dest='client_secret',
        default=os.getenv('CLIENT_SECRET'),
        help='app_secret or suite_secret from https://open-dev.dingtalk.com'
    )
    parser.add_argument(
        '--output-dir',
        dest='output_dir',
        default=os.getenv('OUTPUT_DIR') or DEFAULT_OUTPUT_DIR,
        help='Directory for media file storage and metadata database'
    )
    parser.add_argument(
        '--notify-conversation-id',
        dest='notify_conversation_id',
        default=os.getenv('NOTIFY_CONVERSATION_ID'),
        help='DingTalk openConversationId to send lifecycle online/offline notifications'
    )
    parser.add_argument(
        '--notify-staff-id',
        dest='notify_staff_id',
        default=os.getenv('NOTIFY_STAFF_ID'),
        help='DingTalk senderStaffId (enterprise userId from the raw message '
             'payload) to send lifecycle online/offline notifications'
    )
    # LOG_LEVEL is env-only (no CLI flag), read verbatim; validation and
    # fallback to INFO happen in resolve_log_level() during logger setup.
    parser.set_defaults(log_level=os.getenv('LOG_LEVEL') or DEFAULT_LOG_LEVEL)
    # SEMANTIC_COMMAND_ENABLED is env-only (no CLI flag); the boolean
    # interpretation is owned by the command_matching package.
    parser.set_defaults(
        semantic_command_enabled=parse_enabled(os.getenv('SEMANTIC_COMMAND_ENABLED'))
    )

    options = parser.parse_args(args)

    if not options.client_id or not options.client_secret:
        parser.error(
            'client_id and client_secret must be set via command-line arguments '
            '(--client-id, --client-secret) or environment variables (CLIENT_ID, CLIENT_SECRET)'
        )
    return options


def create_pipeline(
    output_dir: str,
    metadata_store: MetadataStore,
    dingtalk_client,
    matcher,
    logger: Optional[logging.Logger] = None,
) -> PipelineHandler:
    """Construct and configure the message pipeline with handlers."""
    file_downloader = FileDownloader(
        output_dir=output_dir,
        dingtalk_client=dingtalk_client,
        logger=logger,
    )

    command_logger = logger if logger is not None else logging.getLogger("file-bridge")

    async def rebuild_index(message, raw_data) -> str:
        command_logger.info("Received rebuild index command")
        cleaned, remaining = await metadata_store.async_rebuild_index()
        return f"索引重建完成，清理元数据 {cleaned} 条，现有有效索引 {remaining} 条。"

    dispatch_table = {REBUILD_INDEX: rebuild_index}

    pipeline = PipelineHandler(
        handlers=[
            CommandHandler(
                matcher=matcher,
                dispatch_table=dispatch_table,
                logger=logger,
            ),
            MediaFileHandler(
                output_dir=output_dir,
                metadata_store=metadata_store,
                file_downloader=file_downloader,
                logger=logger,
            ),
        ],
        logger=logger,
        storage_probe=partial(write_activity_file, output_dir),
    )
    return pipeline


def run_startup_index_check(metadata_store: MetadataStore, logger: logging.Logger) -> None:
    """Startup phase: reconcile the index against disk and log the counts."""
    cleaned, remaining = metadata_store.rebuild_index()
    logger.info("Index rebuilt: cleaned %d records, %d records remain", cleaned, remaining)


def log_startup_summary(config: argparse.Namespace, logger: logging.Logger) -> None:
    """Emit the version line and the effective configuration summary at INFO.

    Printed after logger setup and before the DingTalk connection is opened, so
    operators can confirm which build and which bot/options are running from
    the first lines of the log. client_secret is deliberately never read here.
    """
    logger.info("File Bridge starting: version=%s", get_app_version())

    semantic = "on (semantic)" if config.semantic_command_enabled else "off (substring)"
    if config.notify_staff_id:
        notify_staff = f"on (staff={config.notify_staff_id})"
    else:
        notify_staff = "off"
    if config.notify_conversation_id:
        notify_group = f"on (conversation={config.notify_conversation_id})"
    else:
        notify_group = "off"

    logger.info(
        "Configuration: client_id=%s, log_level=%s, semantic_command=%s, "
        "notify_staff=%s, notify_group=%s, output_dir=%s",
        config.client_id,
        config.log_level,
        semantic,
        notify_staff,
        notify_group,
        config.output_dir,
    )


def main(args=None):
    # Load .env only at the product entry point; importing this module must
    # stay side-effect free so tests never inherit local environment values.
    dotenv.load_dotenv()

    config = parse_config(args)
    logger = setup_logger(config.log_level)
    log_startup_summary(config, logger)

    credential = dingtalk_stream.Credential(config.client_id, config.client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential, logger=logger)

    metadata_store = MetadataStore(output_dir=config.output_dir)
    run_startup_index_check(metadata_store, logger)

    matcher = build_command_matcher(enabled=config.semantic_command_enabled)
    pipeline = create_pipeline(config.output_dir, metadata_store, client, matcher, logger)
    client.register_callback_handler(dingtalk_stream.chatbot.ChatbotMessage.TOPIC, pipeline)

    notifier = LifecycleNotifier(
        dingtalk_client=client,
        notify_conversation_id=config.notify_conversation_id,
        notify_staff_id=config.notify_staff_id,
        logger=logger,
    )
    runner = BotService(client=client, notifier=notifier, logger=logger, pipeline=pipeline)
    runner.run_forever()


if __name__ == '__main__':
    main()
