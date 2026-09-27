# !/usr/bin/env python

import argparse
import logging
import os
from typing import List, Optional
import dingtalk_stream
import dotenv

from app.services.metadata_store import MetadataStore
from app.services.file_downloader import FileDownloader
from app.services.lifecycle_notifier import LifecycleNotifier
from app.core.runner import BotService
from app.handlers import (
    PipelineHandler,
    CommandHandler,
    MediaFileHandler,
    CalcBotFallbackHandler,
)

dotenv.load_dotenv()

DEFAULT_OUTPUT_DIR = "./output"
DEFAULT_LOG_LEVEL = "INFO"

LOG_FORMAT = '%(asctime)s %(name)-8s %(levelname)-8s %(message)s [%(filename)s:%(lineno)d]'

LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


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
    """
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
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

    options = parser.parse_args(args)

    if not options.client_id or not options.client_secret:
        parser.error(
            'client_id and client_secret must be set via command-line arguments '
            '(--client-id, --client-secret) or environment variables (CLIENT_ID, CLIENT_SECRET)'
        )
    return options


def create_pipeline(
    output_dir: str,
    dingtalk_client,
    logger: Optional[logging.Logger] = None,
) -> PipelineHandler:
    """Construct and configure the message pipeline with handlers."""
    metadata_store = MetadataStore(output_dir=output_dir)
    file_downloader = FileDownloader(
        output_dir=output_dir,
        dingtalk_client=dingtalk_client,
        logger=logger,
    )

    pipeline = PipelineHandler(
        handlers=[
            CommandHandler(metadata_store=metadata_store, logger=logger),
            MediaFileHandler(
                output_dir=output_dir,
                metadata_store=metadata_store,
                file_downloader=file_downloader,
                logger=logger,
            ),
            CalcBotFallbackHandler(logger=logger),
        ],
        logger=logger,
    )
    return pipeline


def main(args=None):
    config = parse_config(args)
    logger = setup_logger(config.log_level)

    credential = dingtalk_stream.Credential(config.client_id, config.client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential, logger=logger)

    pipeline = create_pipeline(config.output_dir, client, logger)
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
