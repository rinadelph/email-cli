"""Utility helpers."""

from datetime import datetime
from typing import Optional


def resolve_account_name(name: Optional[str]) -> str:
    """Resolve account name from explicit arg or default."""
    from email_cli.config import get_default_account_name, list_account_names

    if name:
        return name
    default = get_default_account_name()
    if default:
        return default
    names = list_account_names()
    if not names:
        raise RuntimeError(
            "No accounts configured. Run 'email accounts add <name> <email>' first."
        )
    return names[0]
