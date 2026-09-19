"""Talking to one lock: the transport seam, the session and the owner flows.

transport.py is the Protocol a Bluetooth stack implements, session.py runs
the key exchange and one encrypted command at a time over it, auth.py logs
in as the owner, and enrollment.py takes over a factory-reset lock. const.py
holds what these need beyond the wire format: GATT UUIDs, timing, the
connect firmware floor and the factory credential.

This package imports no submodule of its own; the public API is
ble/__init__.py.
"""
