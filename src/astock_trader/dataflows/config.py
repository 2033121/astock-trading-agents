"""Global configuration singleton for dataflows.

Provides a simple, module-level config dictionary that can be set
from the application entry point and read by any data provider module.
"""

from typing import Any, Dict

_config: Dict[str, Any] = {}


def set_config(config: Dict[str, Any] | None) -> None:
    """Set the global configuration dictionary.

    Args:
        config: Configuration dict. Pass ``None`` or ``{}`` to reset.
    """
    global _config
    _config = config or {}


def get_config() -> Dict[str, Any]:
    """Return the current global configuration dictionary."""
    return _config
