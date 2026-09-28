"""Unit tests for startup index rebuild behavior in main()."""

from unittest.mock import patch
import pytest
from app.main import main


def test_startup_index_rebuild_logs_counts(caplog):
    """Verify that main() calls rebuild_index() and logs cleaned/remaining counts."""
    env_vars = {
        "CLIENT_ID": "test_id",
        "CLIENT_SECRET": "test_secret",
        "OUTPUT_DIR": "/tmp/test_output",
    }
    with patch.dict("os.environ", env_vars), \
            patch("app.main.MetadataStore") as MockStore, \
            patch("app.main.dingtalk_stream"), \
            patch("app.main.create_pipeline"), \
            patch("app.main.LifecycleNotifier"), \
            patch("app.main.BotService") as mock_runner:

        mock_store_inst = MockStore.return_value
        mock_store_inst.rebuild_index.return_value = (3, 10)

        mock_runner_inst = mock_runner.return_value
        mock_runner_inst.run_forever.side_effect = SystemExit(0)

        with caplog.at_level("INFO"), pytest.raises(SystemExit):
            main([])

        mock_store_inst.rebuild_index.assert_called_once()
        assert "Index rebuilt: cleaned 3 records, 10 records remain" in caplog.text
