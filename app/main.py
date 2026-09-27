# !/usr/bin/env python

import argparse
import logging
import os
from typing import List, Optional
import dingtalk_stream
import dotenv

from lib.metadata_store import MetadataStore
from lib.file_downloader import FileDownloader
from lib.lifecycle_notifier import LifecycleNotifier
from lib.runner import BotService
from lib.handlers import (
    PipelineHandler,
    CommandHandler,
    MediaFileHandler,
    CalcBotFallbackHandler,
)

dotenv.load_dotenv()

DEFAULT_OUTPUT_DIR = "./output"


def setup_logger():
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("file-bridge")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter('%(asctime)s %(name)-8s %(levelname)-8s %(message)s [%(filename)s:%(lineno)d]')
        )
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
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
        '--notify-user-id',
        dest='notify_user_id',
        default=os.getenv('NOTIFY_USER_ID'),
        help='DingTalk userId (staffId) to send lifecycle online/offline notifications'
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
    dingtalk_client,
    logger: Optional[logging.Logger] = None,
) -> PipelineHandler:
    """Construct and configure the message pipeline with handlers."""
    metadata_store = MetadataStore(output_dir=output_dir)
    file_downloader = FileDownloader(output_dir=output_dir, dingtalk_client=dingtalk_client)

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
    logger = setup_logger()
    config = parse_config(args)

    credential = dingtalk_stream.Credential(config.client_id, config.client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)

    pipeline = create_pipeline(config.output_dir, client, logger)
    client.register_callback_handler(dingtalk_stream.chatbot.ChatbotMessage.TOPIC, pipeline)

    notifier = LifecycleNotifier(
        dingtalk_client=client,
        notify_conversation_id=config.notify_conversation_id,
        notify_user_id=config.notify_user_id,
        logger=logger,
    )
    runner = BotService(client=client, notifier=notifier, logger=logger)
    runner.run_forever()


if __name__ == '__main__':
    main()
