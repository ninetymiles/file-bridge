"""Command-line adapter for the photo review service.

Thin by design: parse one image path, resolve gateway settings from the
environment (``.env`` is loaded here and only here), call the service, and map
the outcome to an exit code. All review logic lives in
``app.services.photo_review`` so the message pipeline can reuse it unchanged.
"""

import argparse
import asyncio
import os
import sys
from typing import Callable, List, Mapping, Optional
from pathlib import Path

import dotenv

# 将工程根目录添加到 sys.path，保障直接通过脚本路径执行时能定位到 lib 模块
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.photo_review import (
    ENV_MODEL,
    PhotoReviewer,
    ReviewConfig,
    ReviewConfigError,
)

EXIT_OK = 0
EXIT_REVIEW_FAILED = 1
EXIT_USAGE = 2

REVIEW_FAILED_MESSAGE = (
    "点评失败：网关未返回可用结果，请检查 OPENAI_BASE_URL、模型名以及网关日志。"
)

ReviewFactory = Callable[..., PhotoReviewer]


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser: one image path plus an optional model override."""
    parser = argparse.ArgumentParser(
        prog="script.review",
        description=(
            "Ask a vision model for an aesthetic review of a photo "
            "(analysis plus praise)."
        ),
    )
    parser.add_argument("image", help="Path to the photo to review")
    parser.add_argument(
        "--model",
        dest="model",
        default=None,
        help="Model alias; overrides OPENAI_MODEL",
    )
    return parser


async def _review(
    review_factory: ReviewFactory, config: ReviewConfig, image_path: str
) -> Optional[str]:
    """Run one review, keeping the async boundary out of ``main``."""
    reviewer = review_factory(config.base_url, config.api_key, config.model)
    return await reviewer.review(image_path)


def main(
    argv: Optional[List[str]] = None,
    env: Optional[Mapping[str, str]] = None,
    review_factory: Optional[ReviewFactory] = None,
) -> int:
    """Run the CLI and return the process exit code.

    ``env`` and ``review_factory`` exist so tests can drive the whole command
    without mutating ``os.environ`` or reaching a real gateway. When ``env`` is
    omitted, ``.env`` is loaded and the process environment is used.
    """
    if env is None:
        # Product entry point: load .env once, matching app/main.py.
        dotenv.load_dotenv()
        env = os.environ

    args = build_parser().parse_args(argv)

    if not os.path.isfile(args.image):
        print(f"图片不可读：{args.image}", file=sys.stderr)
        return EXIT_REVIEW_FAILED

    overrides = {ENV_MODEL: args.model} if args.model else {}
    try:
        config = ReviewConfig.from_env({**env, **overrides})
    except ReviewConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return EXIT_USAGE

    factory = review_factory or PhotoReviewer
    text = asyncio.run(_review(factory, config, args.image))

    if not text:
        print(REVIEW_FAILED_MESSAGE, file=sys.stderr)
        return EXIT_REVIEW_FAILED

    print(text)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
