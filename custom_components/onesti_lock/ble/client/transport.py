"""The seam between the protocol and a Bluetooth stack.

Session speaks to the lock through a Transport and knows nothing else about
the radio. A Transport is connected to one lock when the session gets it and
does four things, all on the GATT side of the link: read the firmware revision,
subscribe to the communication characteristic, write to it, and let go.
Scanning, connecting and MTU negotiation stay with whoever builds the
Transport. bleak_transport.py implements it over bleak, and Home Assistant's
bluetooth integration hands out bleak clients too; tests use the fake lock in
tests/ble/fake_lock.py.

The app does the same steps in the same order (NimlyEkeyDeviceBase.connect):
request MTU 23, discover services, read the Software Revision String, enable
notifications on the communication characteristic, then start the key
exchange. Session frames its writes for MTU 23 unless it is given another mtu,
and it never learns what the link negotiated: the app never sends anything
larger, and nothing says the lock takes it. No other value has been tried
against a lock; the parameter exists so that can be tested.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

# The characteristics are COMMUNICATION_CHARACTERISTIC_UUID and
# SOFTWARE_REVISION_CHARACTERISTIC_UUID in client/const.py.

# Called with the bytes of each notification from the communication
# characteristic, one Layer 1 packet per call, in the order they arrived.
type NotificationCallback = Callable[[bytes], None]
# Called once when the link drops without Session asking for it.
type DisconnectCallback = Callable[[], None]


class Transport(Protocol):
    """One connected lock, as the session needs it.

    Every method may raise BleDisconnectedError when the link is gone; any
    other failure should be a BleError subclass too, so a caller can catch the
    library as a whole. The callbacks are plain functions called on the event
    loop the session runs on, and they never block.
    """

    async def read_software_revision(self) -> bytes:
        """The raw value of the Software Revision String (0x2A28), such as b"4.8.2"."""

    async def start_notify(self, on_notification: NotificationCallback, on_disconnect: DisconnectCallback) -> None:
        """Subscribe to the communication characteristic.

        on_notification gets each notification's value; on_disconnect is
        called if the link drops while subscribed.
        """

    async def write(self, data: bytes) -> None:
        """Write one packet to the communication characteristic.

        Returns once the write is done, so the next packet of a blob goes out
        only after the previous one landed, as in PayloadStream. The app
        leaves the write type at the characteristic's default, which Android
        makes a write with response when the characteristic allows one; which
        properties the lock's characteristic has is not recorded.
        """

    async def close(self) -> None:
        """Unsubscribe and disconnect. Safe to call more than once."""
