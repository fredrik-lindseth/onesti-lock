"""redact_digits: the mask every send-path log message goes through."""
from __future__ import annotations

from .conftest import load_component_module

redact = load_component_module("redact")
pin_rules = load_component_module("pin_rules")


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


class TestMaskCoversEveryAcceptedPin:
    """No PIN pin_rules accepts may be short enough to escape the mask.

    A lock may report a MinPINCodeLength below 4. pin_rules raises it to its
    floor, and the mask starts at that same floor, so the two cannot drift.
    """

    def test_shortest_accepted_pin_is_masked(self):
        for reported_min in range(0, 21):
            low, _ = pin_rules.pin_length_range({"min_pin_length": reported_min, "max_pin_length": 8})
            code = "7" * low
            assert pin_rules.is_valid_pin(code, {"min_pin_length": reported_min, "max_pin_length": 8})
            assert code not in redact.redact_digits(f"params {{'pin_code': '{code}'}}"), reported_min

    def test_mask_starts_at_the_pin_floor(self):
        floor = pin_rules.PIN_LENGTH_SANE_MIN
        assert redact.redact_digits("7" * floor) == redact.MASK
        assert redact.redact_digits("7" * (floor - 1)) == "7" * (floor - 1)

    def test_three_digit_slot_numbers_stay_readable(self):
        # The reason the floor sits in pin_rules and not lower in the mask.
        assert redact.redact_digits("slot 999 rejected") == "slot 999 rejected"
