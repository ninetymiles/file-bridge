"""Unit tests for configuration parsing."""

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from app.main import (
    parse_config,
    resolve_log_level,
    setup_logger,
    get_app_version,
    log_startup_summary,
)


def test_default_output_dir(monkeypatch):
    monkeypatch.delenv("OUTPUT_DIR", raising=False)
    monkeypatch.setenv("CLIENT_ID", "test_id")
    monkeypatch.setenv("CLIENT_SECRET", "test_secret")

    config = parse_config([])
    assert config.client_id == "test_id"
    assert config.client_secret == "test_secret"
    assert config.output_dir == "./output"


def test_env_output_dir(monkeypatch):
    monkeypatch.setenv("CLIENT_ID", "test_id")
    monkeypatch.setenv("CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("OUTPUT_DIR", "/path/to/files")

    config = parse_config([])
    assert config.output_dir == "/path/to/files"


def test_cli_output_dir_overrides_env(monkeypatch):
    monkeypatch.setenv("CLIENT_ID", "test_id")
    monkeypatch.setenv("CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("OUTPUT_DIR", "/path/to/files")

    config = parse_config(["--output-dir", "/custom/path"])
    assert config.output_dir == "/custom/path"


def test_cli_credentials_override_env(monkeypatch):
    monkeypatch.setenv("CLIENT_ID", "env_id")
    monkeypatch.setenv("CLIENT_SECRET", "env_secret")

    config = parse_config(["--client-id", "cli_id", "--client-secret", "cli_secret"])
    assert config.client_id == "cli_id"
    assert config.client_secret == "cli_secret"


def test_missing_credentials_raises_error(monkeypatch):
    monkeypatch.delenv("CLIENT_ID", raising=False)
    monkeypatch.delenv("CLIENT_SECRET", raising=False)

    with pytest.raises(SystemExit):
        parse_config([])


def test_env_notification_config(monkeypatch):
    monkeypatch.setenv("CLIENT_ID", "test_id")
    monkeypatch.setenv("CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("NOTIFY_CONVERSATION_ID", "cid123")
    monkeypatch.setenv("NOTIFY_STAFF_ID", "staff456")

    config = parse_config([])
    assert config.notify_conversation_id == "cid123"
    assert config.notify_staff_id == "staff456"


def test_cli_notification_config_overrides_env(monkeypatch):
    monkeypatch.setenv("CLIENT_ID", "test_id")
    monkeypatch.setenv("CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("NOTIFY_CONVERSATION_ID", "cid_env")
    monkeypatch.setenv("NOTIFY_STAFF_ID", "staff_env")

    config = parse_config([
        "--notify-conversation-id", "cid_cli",
        "--notify-staff-id", "staff_cli"
    ])
    assert config.notify_conversation_id == "cid_cli"
    assert config.notify_staff_id == "staff_cli"


def test_unconfigured_notification_config(monkeypatch):
    monkeypatch.delenv("NOTIFY_CONVERSATION_ID", raising=False)
    monkeypatch.delenv("NOTIFY_STAFF_ID", raising=False)
    monkeypatch.setenv("CLIENT_ID", "test_id")
    monkeypatch.setenv("CLIENT_SECRET", "test_secret")

    config = parse_config([])
    assert config.notify_conversation_id is None
    assert config.notify_staff_id is None


def test_default_log_level(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.setenv("CLIENT_ID", "test_id")
    monkeypatch.setenv("CLIENT_SECRET", "test_secret")

    config = parse_config([])
    assert config.log_level == "INFO"


def test_log_level_read_verbatim_from_env(monkeypatch):
    monkeypatch.setenv("CLIENT_ID", "test_id")
    monkeypatch.setenv("CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    config = parse_config([])
    assert config.log_level == "debug"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("DEBUG", logging.DEBUG),
        ("INFO", logging.INFO),
        ("WARNING", logging.WARNING),
        ("ERROR", logging.ERROR),
        ("debug", logging.DEBUG),
        ("  Warning ", logging.WARNING),
        ("VERBOSE", logging.INFO),
        ("", logging.INFO),
        (None, logging.INFO),
    ],
)
def test_resolve_log_level(raw, expected):
    assert resolve_log_level(raw) == expected


def test_setup_logger_applies_debug_level():
    logger = setup_logger("debug")
    assert logger.level == logging.DEBUG


def test_setup_logger_invalid_level_warns_and_falls_back(caplog):
    with caplog.at_level(logging.DEBUG, logger="file-bridge"):
        logger = setup_logger("verbose")
        assert logger.level == logging.INFO
        assert "Invalid LOG_LEVEL 'verbose'" in caplog.text


def test_semantic_command_enabled_defaults_off(monkeypatch):
    monkeypatch.delenv("SEMANTIC_COMMAND_ENABLED", raising=False)
    monkeypatch.setenv("CLIENT_ID", "test_id")
    monkeypatch.setenv("CLIENT_SECRET", "test_secret")

    config = parse_config([])
    assert config.semantic_command_enabled is False


def test_semantic_command_enabled_read_from_env(monkeypatch):
    monkeypatch.setenv("CLIENT_ID", "test_id")
    monkeypatch.setenv("CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("SEMANTIC_COMMAND_ENABLED", "true")

    config = parse_config([])
    assert config.semantic_command_enabled is True


def test_importing_app_main_does_not_load_dotenv():
    """Importing app.main must be side-effect free and never load .env.

    Runs in a clean subprocess at the project root. With a local .env setting
    SEMANTIC_COMMAND_ENABLED, an import-time load_dotenv() would surface as
    the variable appearing after import; with no .env (CI) the assertion holds
    trivially.
    """
    project_root = Path(__file__).resolve().parents[1]
    clean_env = {
        key: value for key, value in os.environ.items()
        if key != "SEMANTIC_COMMAND_ENABLED"
    }
    code = (
        "import os\n"
        "assert 'SEMANTIC_COMMAND_ENABLED' not in os.environ\n"
        "import app.main\n"
        "assert 'SEMANTIC_COMMAND_ENABLED' not in os.environ\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project_root,
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_get_app_version_returns_env_value(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    assert get_app_version() == "1.2.3"


def test_get_app_version_empty_string_falls_back_to_dev(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "")
    assert get_app_version() == "dev"


def test_get_app_version_unset_falls_back_to_dev(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    assert get_app_version() == "dev"


def _make_config(**overrides):
    base = dict(
        client_id="cid_123",
        client_secret="super_secret_value",
        log_level="INFO",
        semantic_command_enabled=False,
        notify_staff_id=None,
        notify_conversation_id=None,
        output_dir="./output",
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_log_startup_summary_all_off(monkeypatch, caplog):
    monkeypatch.delenv("APP_VERSION", raising=False)
    config = _make_config()
    with caplog.at_level(logging.INFO, logger="file-bridge"):
        log_startup_summary(config, logging.getLogger("file-bridge"))

    text = caplog.text
    assert "File Bridge starting: version=dev" in text
    assert "client_id=cid_123" in text
    assert "log_level=INFO" in text
    assert "semantic_command=off (substring)" in text
    assert "notify_staff=off" in text
    assert "notify_group=off" in text
    assert "output_dir=./output" in text
    # Secret must never appear in startup logs.
    assert "super_secret_value" not in text


def test_log_startup_summary_all_on(monkeypatch, caplog):
    monkeypatch.setenv("APP_VERSION", "1.2.0")
    config = _make_config(
        semantic_command_enabled=True,
        notify_staff_id="staff_001",
        notify_conversation_id="conv_abc",
    )
    with caplog.at_level(logging.INFO, logger="file-bridge"):
        log_startup_summary(config, logging.getLogger("file-bridge"))

    text = caplog.text
    assert "File Bridge starting: version=1.2.0" in text
    assert "semantic_command=on (semantic)" in text
    assert "notify_staff=on (staff=staff_001)" in text
    assert "notify_group=on (conversation=conv_abc)" in text
    assert "super_secret_value" not in text


def _make_stream_record(msg: str, level: int = logging.INFO) -> logging.LogRecord:
    record = logging.LogRecord(
        name="file-bridge",
        level=level,
        pathname="/app/.venv/lib/python3.14/site-packages/dingtalk_stream/stream.py",
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    record.filename = "stream.py"
    return record


@pytest.fixture
def configured_logs():
    """Attach a capture handler to the root logger and configure logging.

    The handler is added before ``setup_logger`` so it receives the same
    stream-log filter as every other root handler; tests then observe what a
    configured application actually emits.
    """
    records = []
    capture = logging.Handler()
    capture.emit = records.append
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(capture)
    try:
        setup_logger("DEBUG")
        yield records
    finally:
        root.removeHandler(capture)
        root.setLevel(previous_level)


def _emit(record: logging.LogRecord) -> None:
    logging.getLogger("file-bridge").handle(record)


def test_stream_disconnect_log_is_rewritten_to_conclusion(configured_logs):
    _emit(
        _make_stream_record(
            "received disconnect topic=disconnect message={'content': 'long json'}"
        )
    )

    assert len(configured_logs) == 1
    assert (
        configured_logs[0].getMessage()
        == "DingTalk stream disconnected: received disconnect message"
    )


def test_stream_endpoint_log_is_rewritten_to_connected(configured_logs):
    _emit(_make_stream_record("endpoint is {'endpoint': 'wss://...', 'ticket': 'abc'}"))

    assert len(configured_logs) == 1
    assert configured_logs[0].getMessage() == "DingTalk stream connected."


def test_open_connection_log_is_downgraded_to_debug(configured_logs):
    _emit(_make_stream_record("open connection, url=wss://dingtalk.example/stream"))

    assert len(configured_logs) == 1
    assert configured_logs[0].levelno == logging.DEBUG


def test_unrelated_stream_log_is_preserved(configured_logs):
    _emit(_make_stream_record("[start] network exception, will retry"))

    assert len(configured_logs) == 1
    assert configured_logs[0].getMessage() == "[start] network exception, will retry"
    assert configured_logs[0].levelno == logging.INFO


def test_non_stream_log_is_preserved(configured_logs):
    record = logging.LogRecord(
        name="file-bridge",
        level=logging.INFO,
        pathname="app/handlers/message.py",
        lineno=1,
        msg="Received private message from alice, type=text",
        args=(),
        exc_info=None,
    )
    record.filename = "message.py"
    _emit(record)

    assert len(configured_logs) == 1
    assert (
        configured_logs[0].getMessage()
        == "Received private message from alice, type=text"
    )


def test_repeated_setup_logger_does_not_duplicate_output(configured_logs):
    setup_logger("DEBUG")
    setup_logger("DEBUG")

    logging.getLogger("file-bridge").info("unique-marker-9d1f")

    assert [r.getMessage() for r in configured_logs] == ["unique-marker-9d1f"]


def test_httpx_info_is_suppressed_but_warning_is_kept(configured_logs):
    httpx_logger = logging.getLogger("httpx")
    httpx_logger.info("GET https://oss.example/signed?token=secret")
    httpx_logger.warning("request failed")

    assert [r.getMessage() for r in configured_logs] == ["request failed"]
