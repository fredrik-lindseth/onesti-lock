"""Checks that key material stays out of error messages and reprs."""
from __future__ import annotations

import pytest

# Distinctive filler, so a leak is easy to spot in a message.
MARKER = bytes([0xA5] * 40)


def assert_no_material(text: str, *secrets: bytes) -> None:
    for secret in secrets:
        assert secret.hex() not in text.lower()
        assert repr(secret) not in text
        assert secret.hex(" ") not in text.lower()


def assert_clean(excinfo: pytest.ExceptionInfo[BaseException], *secrets: bytes) -> None:
    assert_no_material(str(excinfo.value), *secrets)
    assert_no_material(repr(excinfo.value), *secrets)
    # No chained error a traceback would print next to ours.
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ or excinfo.value.__context__ is None
