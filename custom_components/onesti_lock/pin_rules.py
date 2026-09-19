"""Validation rules derived from the lock's reported capabilities.

Pure logic with no Home Assistant imports, so the pytest-only CI can
execute this module directly. PIN length rules are planned to land here
too (see docs/plans/2026-08-23-vurdering-setpin.md).
"""
from __future__ import annotations

from collections.abc import Mapping

from .const import (
    CONF_RESERVED_SLOTS,
    MAX_SLOTS,
    RESERVED_SLOTS_MAX,
    RESERVED_SLOTS_MIN,
    SLOT_FIRST_USER,
)


def first_user_slot(options: Mapping[str, object] | None) -> int:
    """Lowest slot set_pin, clear_pin and clear_slot may touch.

    The number of reserved master slots differs per model. The Touch Pro,
    PRO and Code manuals reserve 000-002 as master codes; the Code Pro
    manual reserves only 000 and documents 001-999 as user codes. The
    reported model string cannot tell them apart (issue #5: a Code Pro
    presented itself as NimlyTwist), so the count is a per-lock option.

    The value is clamped to [RESERVED_SLOTS_MIN, RESERVED_SLOTS_MAX] so
    slot 0 stays protected whatever is stored. A missing or non-numeric
    value falls back to SLOT_FIRST_USER, the conservative default. The
    settings step stores an int, but options can also be edited by hand in
    .storage or come from an older save, so an integral float such as 1.0
    is read as its int rather than thrown away.
    """
    value = (options or {}).get(CONF_RESERVED_SLOTS)
    if isinstance(value, bool):
        return SLOT_FIRST_USER
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int):
        return SLOT_FIRST_USER
    return max(RESERVED_SLOTS_MIN, min(RESERVED_SLOTS_MAX, value))


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
