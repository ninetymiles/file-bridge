"""Contract test for the startup index consistency-check phase."""

import logging
from unittest.mock import Mock

from app.main import run_startup_index_check


def test_run_startup_index_check_calls_rebuild_and_logs_counts(caplog):
    """The phase calls rebuild_index() once and logs cleaned/remaining counts."""
    store = Mock()
    store.rebuild_index.return_value = (3, 10)
    logger = logging.getLogger("file-bridge")

    with caplog.at_level(logging.INFO):
        run_startup_index_check(store, logger)

    store.rebuild_index.assert_called_once_with()
    assert "Index rebuilt: cleaned 3 records, 10 records remain" in caplog.text
