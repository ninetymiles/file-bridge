# !/usr/bin/env python

import logging
from typing import Optional
import dingtalk_stream
import dotenv

from lib.config import parse_config, AppConfig
from lib.metadata_store import MetadataStore
from lib.file_downloader import FileDownloader
from lib.handlers import (
    PipelineHandler,
    CommandHandler,
    MediaFileHandler,
    CalcBotFallbackHandler,
)

dotenv.load_dotenv()


def setup_logger():
    logger = logging.getLogger("file-bridge")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter('%(asctime)s %(name)-8s %(levelname)-8s %(message)s [%(filename)s:%(lineno)d]')
        )
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def define_options(args=None) -> AppConfig:
    return parse_config(args)


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
            CommandHandler(metadata_store=metadata_store),
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
    config = define_options(args)

    credential = dingtalk_stream.Credential(config.client_id, config.client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)

    pipeline = create_pipeline(config.output_dir, client, logger)
    client.register_callback_handler(dingtalk_stream.chatbot.ChatbotMessage.TOPIC, pipeline)
    client.start_forever()


if __name__ == '__main__':
    main()
