"""Masking for text that may quote a PIN code, before it reaches a log.

Pure logic with no Home Assistant imports, so the pytest-only CI runs it
directly. Exception messages on the send path are not ours to shape: a
voluptuous vol.Invalid raised by ZHA's service schema quotes the offending
params, pin_code included, and a zigpy error may echo the frame it failed to
send. Every such message goes through redact_digits before it is logged.
"""
from __future__ import annotations

import re

from .pin_rules import PIN_LENGTH_SANE_MIN

# pin_rules never accepts a PIN shorter than PIN_LENGTH_SANE_MIN, whatever the
# lock reports, so any run of that many digits or more is treated as one.
# Shorter runs stay readable: command ids, slot numbers and ZCL status codes
# are what make an error message useful.
_DIGIT_RUN = re.compile(rf"\d{{{PIN_LENGTH_SANE_MIN},}}")
# Fixed width, so the mask does not reveal how long the code was.
MASK = "****"


def redact_digits(text: object) -> str:
    """str(text) with every run of PIN_LENGTH_SANE_MIN or more digits masked."""
    return _DIGIT_RUN.sub(MASK, str(text))
