"""Unit tests for configuration parsing."""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from app.main import parse_config, resolve_log_level, setup_logger


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


def test_setup_logger_attaches_no_private_handler():
    setup_logger()
    app_logger = logging.getLogger("file-bridge")
    assert app_logger.handlers == []


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
