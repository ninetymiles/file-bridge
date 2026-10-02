"""Pytest collection hooks.

The default invocation (``addopts = -m general``) must run every test except
opt-in special sets without requiring manual markers. Pytest's built-in ``-m``
filter would otherwise reject tests that never declare a marker, so the
``general`` expression is handled here directly: it is cleared and special-set
tests are deselected. Explicit expressions such as ``-m semantic`` and
``-m ""`` pass through untouched.
"""

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
