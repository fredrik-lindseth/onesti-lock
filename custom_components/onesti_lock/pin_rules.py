"""Validation rules derived from the lock's reported capabilities.

Pure logic with no Home Assistant imports, so the pytest-only CI can
execute this module directly. PIN length rules are planned to land here
too (see docs/plans/2026-08-23-vurdering-setpin.md).
"""
from __future__ import annotations

from collections.abc import Mapping

from .const import MAX_SLOTS, SLOT_FIRST_USER


def max_user_slot(capabilities: Mapping[str, object] | None) -> int:
    """Highest slot number set_pin should accept.

    The ceiling comes from ZCL semantics: NumberOfPINUsersSupported is a
    count, not a top index, so the valid user ids are 0 to N-1 and the
    highest usable slot is N-1. NimlyPRO and NimlyCodePRO both report 50
    (device interview in z2m #31385, see commit d6022ce),
    but no slot above that has actually been observed being rejected by
    real hardware, and the manual documents 3-999, so the attribute is
    only trusted when it has been read and is a sane int leaving room for
    at least one user slot. Anything missing, zero or nonsensical falls
    back to the manual's range: we never refuse on evidence we lack.
    """
    caps = capabilities or {}
    num = caps.get("num_pin_users")
    if isinstance(num, int) and SLOT_FIRST_USER < num <= MAX_SLOTS:
        return num - 1
    return MAX_SLOTS - 1
