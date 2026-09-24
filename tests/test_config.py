"""Unit tests for configuration parsing."""

import pytest
from lib.config import parse_config, DEFAULT_OUTPUT_DIR


def test_default_output_dir(monkeypatch):
    monkeypatch.delenv("OUTPUT_DIR", raising=False)
    monkeypatch.setenv("CLIENT_ID", "test_id")
    monkeypatch.setenv("CLIENT_SECRET", "test_secret")

    config = parse_config([])
    assert config.client_id == "test_id"
    assert config.client_secret == "test_secret"
    assert config.output_dir == DEFAULT_OUTPUT_DIR


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


def test_missing_credentials_raises_error(monkeypatch):
    monkeypatch.delenv("CLIENT_ID", raising=False)
    monkeypatch.delenv("CLIENT_SECRET", raising=False)

    with pytest.raises(SystemExit):
        parse_config([])


def test_env_notification_config(monkeypatch):
    monkeypatch.setenv("CLIENT_ID", "test_id")
    monkeypatch.setenv("CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("NOTIFY_CONVERSATION_ID", "cid123")
    monkeypatch.setenv("NOTIFY_USER_ID", "user456")

    config = parse_config([])
    assert config.notify_conversation_id == "cid123"
    assert config.notify_user_id == "user456"


def test_cli_notification_config_overrides_env(monkeypatch):
    monkeypatch.setenv("CLIENT_ID", "test_id")
    monkeypatch.setenv("CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("NOTIFY_CONVERSATION_ID", "cid_env")
    monkeypatch.setenv("NOTIFY_USER_ID", "user_env")

    config = parse_config([
        "--notify-conversation-id", "cid_cli",
        "--notify-user-id", "user_cli"
    ])
    assert config.notify_conversation_id == "cid_cli"
    assert config.notify_user_id == "user_cli"


def test_unconfigured_notification_config(monkeypatch):
    monkeypatch.delenv("NOTIFY_CONVERSATION_ID", raising=False)
    monkeypatch.delenv("NOTIFY_USER_ID", raising=False)
    monkeypatch.setenv("CLIENT_ID", "test_id")
    monkeypatch.setenv("CLIENT_SECRET", "test_secret")

    config = parse_config([])
    assert config.notify_conversation_id is None
    assert config.notify_user_id is None
