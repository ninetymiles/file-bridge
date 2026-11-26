"""Contract test for the startup index consistency-check phase."""

from unittest.mock import Mock

from app.main import run_startup_index_check


def test_run_startup_index_check_calls_rebuild_once():
    """The phase calls rebuild_index() exactly once."""
    store = Mock()
    store.rebuild_index.return_value = (3, 10)

    run_startup_index_check(store, Mock())

    store.rebuild_index.assert_called_once_with()
