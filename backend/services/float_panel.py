"""Start the floating usage widget.

The widget reads the local collector over loopback, so the collector has to be
running. PySide6 ships with Token Observatory; if it is missing this explains
how to restore it instead of failing with a stack trace.
"""
import importlib
import sys

INSTALL_HINT = "The floating widget needs PySide6. Reinstall Token Observatory, or run: pip install 'PySide6-Essentials>=6.5,<7'"


def available():
    """True when the widget's toolkit is installed."""
    try:
        importlib.import_module('PySide6.QtWidgets')
        return True
    except ImportError:
        return False


def run(url, position_file=None):
    """Show the widget until it is closed. Returns an exit code."""
    try:
        window = importlib.import_module('backend.services.float_window')
    except ImportError:
        print(INSTALL_HINT, file=sys.stderr)
        return 1
    return window.run(url, position_file=position_file)
