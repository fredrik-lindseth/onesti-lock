"""The wire format: frames, ids and payloads, with no crypto and no I/O.

Layer 1 packets and blobs (packet.py, blob.py), Layer 2 commands
(command.py) with a builder per command (commands.py) and the app's firmware
and model gates for each (features.py), Layer 3 responses
(response.py) with a parser per answer (responses.py), the advertisement
(advertisement.py), the little-endian field codec they share (streams.py),
and the constants and enums they are built from (const.py).

Encryption plugs into packet.PacketStream through the PayloadCipher protocol
it defines; the cipher itself is in ble/crypto.py. Nothing here imports it.

This package imports no submodule of its own, so importing one of them does
not load the rest. The public API is ble/__init__.py.
"""
