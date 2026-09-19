"""redact_digits: the mask every send-path log message goes through."""
from __future__ import annotations

from .conftest import load_component_module

redact = load_component_module("redact")


class TestRedactDigits:
    def test_masks_a_quoted_pin(self):
        # The shape of vol.Invalid from ZHA's service schema.
        text = redact.redact_digits("params {'pin_code': '83729164'}")
        assert "83729164" not in text
        assert text == "params {'pin_code': '****'}"

    def test_mask_does_not_reveal_the_length(self):
        assert redact.redact_digits("1234") == redact.redact_digits("12345678")

    def test_short_runs_stay_readable(self):
        # Slot numbers, status codes and the like are what make an error
        # useful, and none of them can be a PIN.
        assert redact.redact_digits("slot 5 status 134 ep 11") == "slot 5 status 134 ep 11"

    def test_every_run_is_masked(self):
        assert redact.redact_digits("1234 and 987654") == "**** and ****"

    def test_accepts_any_object(self):
        assert redact.redact_digits(ValueError("code 4321")) == "code ****"
