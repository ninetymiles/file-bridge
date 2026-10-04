"""Pytest collection hooks.

The default invocation (``addopts = -m general``) must run every test except
opt-in special sets without requiring manual markers. Pytest's built-in ``-m``
filter would otherwise reject tests that never declare a marker, so the
``general`` expression is handled here directly: it is cleared and special-set
tests are deselected. Explicit expressions such as ``-m semantic`` and
``-m ""`` pass through untouched.
"""

import sys
import types

# General tests must never load the native fastembed stack. The semantic
# backend module runs ``from fastembed import TextEmbedding`` at import
# (collection) time, before any fixture can execute, so this stub is installed
# here: conftest is imported before the test modules beneath it. Only the
# semantic smoke session pops it at runtime to bind the real inference stack.
if "fastembed" not in sys.modules:
    _fastembed_stub = types.ModuleType("fastembed")

    class _StubTextEmbedding:
        """Records constructor kwargs; general tests never call embed()."""

        def __init__(self, **kwargs):
            self.init_kwargs = kwargs

    _fastembed_stub.TextEmbedding = _StubTextEmbedding
    _fastembed_stub._file_bridge_test_stub = True
    sys.modules["fastembed"] = _fastembed_stub

SPECIAL_MARKERS = {"semantic"}


def pytest_collection_modifyitems(config, items):
    if config.getoption("markexpr", "").strip() != "general":
        return

    config.option.markexpr = ""
    selected = []
    deselected = []
    for item in items:
        special_markers = [
            name
            for name in SPECIAL_MARKERS
            if list(item.iter_markers(name=name))
        ]
        if special_markers:
            deselected.append(item)
        else:
            selected.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = selected
