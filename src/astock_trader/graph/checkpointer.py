"""SQLite checkpoint system for crash recovery.

Each ticker gets its own SQLite database so that checkpoint data is
isolated per stock.  The checkpointer integrates with LangGraph's
``SqliteSaver`` to persist graph execution state at every superstep.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default directory for checkpoint databases
_DEFAULT_CHECKPOINT_DIR = os.path.join(
    os.path.expanduser("~"), ".astock_trader", "checkpoints"
)


def _ensure_dir(directory: str) -> None:
    """Create directory tree if it does not exist."""
    Path(directory).mkdir(parents=True, exist_ok=True)


# ────────────────────────────────────────────────────────────────
#  Public API
# ────────────────────────────────────────────────────────────────

def get_checkpointer(
    ticker: str,
    checkpoint_dir: Optional[str] = None,
) -> Any:
    """Return a ``SqliteSaver`` checkpointer for the given ticker.

    Parameters
    ----------
    ticker : str
        Stock code, e.g. ``"000001"``.  Used to construct the database filename.
    checkpoint_dir : str | None
        Directory for checkpoint databases.  Defaults to
        ``~/.astock_trader/checkpoints/``.

    Returns
    -------
    langgraph.checkpoint.sqlite.SqliteSaver
        A context-manager-compatible checkpointer.  The caller is responsible
        for entering the context (``with get_checkpointer(...) as cp: ...``).
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    directory = checkpoint_dir or _DEFAULT_CHECKPOINT_DIR
    _ensure_dir(directory)
    db_path = os.path.join(directory, f"{ticker}.sqlite")

    logger.debug("Opening checkpointer DB: %s", db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return SqliteSaver(conn)


def has_checkpoint(
    ticker: str,
    checkpoint_dir: Optional[str] = None,
) -> bool:
    """Check whether a checkpoint database exists and contains data.

    Parameters
    ----------
    ticker : str
        Stock code.
    checkpoint_dir : str | None
        Checkpoint directory override.

    Returns
    -------
    bool
        ``True`` if a non-empty checkpoint database exists for *ticker*.
    """
    directory = checkpoint_dir or _DEFAULT_CHECKPOINT_DIR
    db_path = os.path.join(directory, f"{ticker}.sqlite")

    if not os.path.exists(db_path):
        return False

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = cursor.fetchall()
        conn.close()
        return len(tables) > 0
    except Exception:
        return False


def checkpoint_step(
    ticker: str,
    checkpoint_dir: Optional[str] = None,
) -> int:
    """Return the number of checkpointed super-steps for a ticker.

    Parameters
    ----------
    ticker : str
        Stock code.
    checkpoint_dir : str | None
        Checkpoint directory override.

    Returns
    -------
    int
        Number of checkpoint rows, or 0 if no checkpoint exists.
    """
    directory = checkpoint_dir or _DEFAULT_CHECKPOINT_DIR
    db_path = os.path.join(directory, f"{ticker}.sqlite")

    if not os.path.exists(db_path):
        return 0

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='checkpoints'"
        )
        if cursor.fetchone() is None:
            conn.close()
            return 0
        cursor = conn.execute("SELECT COUNT(*) FROM checkpoints")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0


def clear_checkpoint(
    ticker: str,
    checkpoint_dir: Optional[str] = None,
) -> bool:
    """Delete the checkpoint database for a ticker.

    Parameters
    ----------
    ticker : str
        Stock code.
    checkpoint_dir : str | None
        Checkpoint directory override.

    Returns
    -------
    bool
        ``True`` if the database was successfully removed.
    """
    directory = checkpoint_dir or _DEFAULT_CHECKPOINT_DIR
    db_path = os.path.join(directory, f"{ticker}.sqlite")

    if not os.path.exists(db_path):
        return True

    try:
        os.remove(db_path)
        # Also remove WAL / SHM files if present
        for suffix in ("-wal", "-shm"):
            wal = db_path + suffix
            if os.path.exists(wal):
                os.remove(wal)
        logger.info("Cleared checkpoint for %s", ticker)
        return True
    except OSError as exc:
        logger.warning("Failed to clear checkpoint for %s: %s", ticker, exc)
        return False


def thread_id(ticker: str, trade_date: str = "latest") -> str:
    """Construct a deterministic thread identifier for checkpointing.

    Parameters
    ----------
    ticker : str
        Stock code.
    trade_date : str
        Trade date, or ``"latest"`` for a rolling thread.

    Returns
    -------
    str
        Thread identifier string.
    """
    return f"{ticker}_{trade_date}"
