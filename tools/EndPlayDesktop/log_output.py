"""Format pretask messages through the client's existing rich-text support."""
from __future__ import annotations

import html
import logging
import sys


class GuiLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if record.levelno >= logging.ERROR:
            color = "--color-error"
        elif record.levelno >= logging.WARNING:
            color = "--color-warning"
        else:
            color = "--color-info"
        message = html.escape(super().format(record)).replace("\r\n", "\n").replace("\n", "<br>")
        return f'<span style="color: var({color})">{message}</span>'


def configure_logging(*, gui: bool = False) -> None:
    if gui:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(GuiLogFormatter())
        logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    else:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
