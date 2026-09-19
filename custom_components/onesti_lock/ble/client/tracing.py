"""A hook that lets the caller watch every frame a Session sends and receives.

The first sessions against a real lock need a frame log that can explain a
failure afterwards: which packet went out, what came back, which frame was
dropped and why. The library does not write that log itself. It hands each
event to a Tracer the caller passes to Session, and the caller decides what
to keep.

What a tracer sees is not redacted. command() gets the plaintext command, so
PinCodeSet carries the PIN and UserAuthFinalize the challenge answer, and
response() gets the plaintext answer, the owner challenge included. Only the
Layer 1 packets after the key exchange are ciphertext. A tracer that writes
anything to disk or a log must redact it first; the library's own rule of no
secret in a log does not reach into the caller's callback.

The events, in the order a command produces them:

- command(command): the Layer 2 command with its CommandRef, once it is
  framed and before its first packet is written.
- packet_out(data): each Layer 1 packet, just before it is written.
- packet_in(data): each notification's bytes, as they arrived.
- response(response): each Layer 3 response that parsed, events included,
  before it is matched to a command or handed to the event listeners.
- dropped(error, data): a frame the session threw away, with the bytes that
  did not parse: the Layer 1 packet when the framing failed, the decrypted
  Layer 3 payload (zero padding included) when the response did not parse,
  and the response's bytes when an event's payload did not.

The calls run on the event loop, inside the session's receive and send paths,
so a tracer must not block. An exception from one is logged by its type and
swallowed: a broken tracer must not break the session it watches.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from ..errors import BleProtocolError
from ..protocol.command import Command
from ..protocol.response import Response

_LOGGER = logging.getLogger(__name__)


class Tracer(Protocol):
    """Receives every frame event of one Session. See the module docstring."""

    def packet_out(self, data: bytes) -> None:
        """One Layer 1 packet, about to be written to the communication characteristic."""

    def packet_in(self, data: bytes) -> None:
        """One notification from the communication characteristic, as received."""

    def command(self, command: Command) -> None:
        """A command about to be sent, with its CommandRef set."""

    def response(self, response: Response) -> None:
        """A response or event that parsed, before the session acts on it."""

    def dropped(self, error: BleProtocolError, data: bytes) -> None:
        """A frame the session dropped, with the error and the bytes that failed."""


class _NoTracer:
    """What a Session without a tracer calls, so it never has to check for None."""

    def packet_out(self, data: bytes) -> None:
        pass

    def packet_in(self, data: bytes) -> None:
        pass

    def command(self, command: Command) -> None:
        pass

    def response(self, response: Response) -> None:
        pass

    def dropped(self, error: BleProtocolError, data: bytes) -> None:
        pass


class _GuardedTracer:
    """Passes every call on to the caller's tracer and contains its exceptions."""

    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer

    def packet_out(self, data: bytes) -> None:
        _call("packet_out", self._tracer.packet_out, data)

    def packet_in(self, data: bytes) -> None:
        _call("packet_in", self._tracer.packet_in, data)

    def command(self, command: Command) -> None:
        _call("command", self._tracer.command, command)

    def response(self, response: Response) -> None:
        _call("response", self._tracer.response, response)

    def dropped(self, error: BleProtocolError, data: bytes) -> None:
        _call("dropped", self._tracer.dropped, error, data)


def _call[*Ts](event: str, method: Callable[[*Ts], None], *args: *Ts) -> None:
    try:
        method(*args)
    except Exception as err:
        # The tracer is the caller's code and its message could quote the
        # frame it was handed, so only the type is logged, and no traceback.
        _LOGGER.error("The session tracer failed on %s with %s", event, type(err).__name__)


def guarded_tracer(tracer: Tracer | None) -> Tracer:
    """The tracer a Session calls: a no-op for None, else one that cannot raise."""
    if tracer is None:
        return _NoTracer()
    return _GuardedTracer(tracer)
