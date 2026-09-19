"""Offline implementation of the Onesti/Nimly BLE protocol.

Pure Python with no Home Assistant imports, and nothing in the integration
imports it yet: the transport that connects it to a lock comes later. The
protocol is described in docs/nimly-ble-app/, and every value in const.py was
read out of the decompiled Nimly BLE app, not guessed.
"""
