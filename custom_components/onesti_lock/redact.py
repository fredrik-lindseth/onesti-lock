"""Masking for text that may quote a PIN code, before it reaches a log.

Pure logic with no Home Assistant imports, so the pytest-only CI runs it
directly. Exception messages on the send path are not ours to shape: a
voluptuous vol.Invalid raised by ZHA's service schema quotes the offending
params, pin_code included, and a zigpy error may echo the frame it failed to
send. Every such message goes through redact_digits before it is logged.
"""
from __future__ import annotations

import re

# PIN codes on these locks are 4 to 8 digits (pin_rules), so any run of four
# or more digits is treated as one. Shorter runs stay readable: command ids,
# slot numbers and ZCL status codes are what make an error message useful.
_DIGIT_RUN = re.compile(r"\d{4,}")
# Fixed width, so the mask does not reveal how long the code was.
MASK = "****"


def redact_digits(text: object) -> str:
    """str(text) with every run of four or more digits replaced by MASK."""
    return _DIGIT_RUN.sub(MASK, str(text))
