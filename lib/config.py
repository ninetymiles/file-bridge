"""Configuration module for file-bridge."""

import argparse
import os
from dataclasses import dataclass
from typing import List, Optional
import dotenv

dotenv.load_dotenv()

DEFAULT_OUTPUT_DIR = "./output"


@dataclass
class AppConfig:
    client_id: str
    client_secret: str
    output_dir: str = DEFAULT_OUTPUT_DIR
    notify_conversation_id: Optional[str] = None
    notify_user_id: Optional[str] = None


def get_argument_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(description="DingTalk Stream Bot Configuration")
    parser.add_argument(
        '--client_id',
        dest='client_id',
        default=os.getenv('CLIENT_ID'),
        help='app_key or suite_key from https://open-dev.dingtalk.com'
    )
    parser.add_argument(
        '--client_secret',
        dest='client_secret',
        default=os.getenv('CLIENT_SECRET'),
        help='app_secret or suite_secret from https://open-dev.dingtalk.com'
    )
    parser.add_argument(
        '--output-dir',
        dest='output_dir',
        default=None,
        help='Directory for media file storage and metadata database'
    )
    parser.add_argument(
        '--notify-conversation-id',
        '--notify_conversation_id',
        dest='notify_conversation_id',
        default=None,
        help='DingTalk openConversationId to send lifecycle online/offline notifications'
    )
    parser.add_argument(
        '--notify-user-id',
        '--notify_user_id',
        dest='notify_user_id',
        default=None,
        help='DingTalk userId (staffId) to send lifecycle online/offline notifications'
    )
    return parser


def parse_config(args: Optional[List[str]] = None) -> AppConfig:
    """Parse command-line arguments and environment variables into AppConfig."""
    parser = get_argument_parser()
    options = parser.parse_args(args)

    client_id = options.client_id or os.getenv('CLIENT_ID')
    client_secret = options.client_secret or os.getenv('CLIENT_SECRET')

    if not client_id or not client_secret:
        parser.error('client_id and client_secret must be set via command-line arguments or environment variables (CLIENT_ID, CLIENT_SECRET)')

    output_dir = options.output_dir or os.getenv('OUTPUT_DIR') or DEFAULT_OUTPUT_DIR
    notify_conversation_id = options.notify_conversation_id or os.getenv('NOTIFY_CONVERSATION_ID')
    notify_user_id = options.notify_user_id or os.getenv('NOTIFY_USER_ID')

    return AppConfig(
        client_id=client_id,
        client_secret=client_secret,
        output_dir=output_dir,
        notify_conversation_id=notify_conversation_id,
        notify_user_id=notify_user_id,
    )
