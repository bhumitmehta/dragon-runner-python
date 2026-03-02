"""
Centralized logging configuration for the multi-agent testing system.

Usage from any module::

    from .logging_config import get_logger

    logger = get_logger(__name__)           # e.g. python_agent.agents.planner
    logger = get_logger("navigator")        # or a short custom name

All log output goes to:
- **Console** (stderr)  --  coloured by level, concise format.
- **File** (``artifacts/logs/agent.log``)  --  verbose format with timestamps &
  module paths.  Rotated automatically at 5 MB.

Log level is controlled by the ``LOG_LEVEL`` environment variable
(default: ``DEBUG``).
"""


from __future__ import annotations
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── Resolve log directory (same as config.LOGS_DIR) ─────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
_LOGS_DIR = _REPO_ROOT / "python_agent" / "artifacts" / "logs"
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

_LOG_FILE = _LOGS_DIR / "agent.log"

# ── Root logging level from env ─────────────────────────────────────
_LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()

# ── Formatters ──────────────────────────────────────────────────────
_CONSOLE_FMT = "[%(levelname).1s] %(name)s: %(message)s"
_FILE_FMT = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

# ── Shared handlers (created once) ──────────────────────────────────
_handlers_configured = False


def _configure_root_handlers():
    """Attach console + file handlers to the root ``python_agent`` logger."""
    global _handlers_configured
    if _handlers_configured:
        return

    root_logger = logging.getLogger("python_agent")
    root_logger.setLevel(getattr(logging, _LOG_LEVEL, logging.DEBUG))

    # Console handler (stderr)
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(_CONSOLE_FMT))
    root_logger.addHandler(console)

    # Rotating file handler
    file_handler = RotatingFileHandler(
        str(_LOG_FILE),
        maxBytes=5 * 1024 * 1024,   # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FMT, datefmt=_DATE_FMT))
    root_logger.addHandler(file_handler)

    # Prevent propagation to the builtin root logger so we don't double-log
    root_logger.propagate = False

    _handlers_configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a named child logger under the ``python_agent`` namespace.

    The first call also initialises the shared console + file handlers.

    Parameters
    ----------
    name : str
        Logger name  --  typically ``__name__`` or a short label like
        ``"orchestrator"``.  If it does not start with ``python_agent.``
        it is prepended automatically.

    Returns
    -------
    logging.Logger
    """
    _configure_root_handlers()

    if not name.startswith("python_agent"):
        name = f"python_agent.{name}"
    return logging.getLogger(name)
