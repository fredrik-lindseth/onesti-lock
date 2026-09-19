"""Validation rules derived from the lock's reported capabilities.

Pure logic with no Home Assistant imports, so the pytest-only CI can
execute this module directly. The services and the options flow both ask
this module which slots and which PIN codes a lock takes.
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

# PIN length when the lock has not reported a sane MinPINCodeLength and
# MaxPINCodeLength. 4-8 is what NimlyPRO reports, and what the Nimly BLE app
# enforces.
PIN_LENGTH_FALLBACK = (4, 8)
# Anything longer is taken as a garbled read rather than a real limit. ZCL
# allows up to 255, but no keypad lock in the Onesti range comes close.
PIN_LENGTH_SANE_MAX = 20


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


def _reported_length(value: object) -> int | None:
    """A reported length attribute, or None when it is missing or not sane."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not 1 <= value <= PIN_LENGTH_SANE_MAX:
        return None
    return value


def pin_length_range(capabilities: Mapping[str, object] | None) -> tuple[int, int]:
    """Shortest and longest PIN code the lock accepts, as (min, max).

    Read from min_pin_length and max_pin_length (ZCL 0x0018 and 0x0017).
    Each bound falls back on its own to PIN_LENGTH_FALLBACK when it is
    missing, not an int, below 1 or above PIN_LENGTH_SANE_MAX. If the two
    left over contradict each other (min above max), neither is trusted and
    the whole fallback range applies.
    """
    caps = capabilities or {}
    low = _reported_length(caps.get("min_pin_length"))
    high = _reported_length(caps.get("max_pin_length"))
    low = PIN_LENGTH_FALLBACK[0] if low is None else low
    high = PIN_LENGTH_FALLBACK[1] if high is None else high
    if low > high:
        return PIN_LENGTH_FALLBACK
    return low, high


def is_valid_pin(code: str, capabilities: Mapping[str, object] | None) -> bool:
    """Whether code is all ASCII digits and within the lock's length range.

    str.isdigit alone would let through superscripts and non-Latin digits,
    which no keypad can type.
    """
    low, high = pin_length_range(capabilities)
    return code.isascii() and code.isdigit() and low <= len(code) <= high
