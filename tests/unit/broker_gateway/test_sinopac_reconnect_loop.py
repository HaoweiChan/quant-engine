"""Tests for the background Sinopac reconnect supervisor (Phase 4)."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from src.broker_gateway.sinopac import SinopacGateway


@pytest.mark.asyncio
async def test_loop_calls_reconnect_on_disconnected_state() -> None:
    """When ``is_connected`` is False, the loop must call the reconnect helper."""
    gw = SinopacGateway()
    gw._connected = False
    gw._ip_blocked = False
    # Use a fast interval so the test doesn't wait the production 20s.
    gw._reconnect_interval_secs = 0.05
    calls: list[int] = []

    def _stub_reconnect():
        calls.append(1)

    with patch.object(gw, "_maybe_reconnect_disconnected", side_effect=_stub_reconnect):
        gw.start_reconnect_loop()
        await asyncio.sleep(0.15)
        gw.stop_reconnect_loop()
    assert len(calls) >= 2  # at least two ticks within 150ms at 50ms interval


@pytest.mark.asyncio
async def test_loop_skips_when_connected() -> None:
    """When already connected, the loop must NOT attempt reconnect."""
    gw = SinopacGateway()
    gw._connected = True
    gw._reconnect_interval_secs = 0.05
    calls: list[int] = []

    def _stub_reconnect():
        calls.append(1)

    with patch.object(gw, "_maybe_reconnect_disconnected", side_effect=_stub_reconnect):
        gw.start_reconnect_loop()
        await asyncio.sleep(0.15)
        gw.stop_reconnect_loop()
    assert calls == []


@pytest.mark.asyncio
async def test_loop_skips_when_ip_blocked() -> None:
    """When the gateway has flagged itself IP-blocked, no reconnect attempts fire.

    Retrying an IP-blocked Sinopac account just spams the broker and
    risks escalating the block; the operator must whitelist first.
    """
    gw = SinopacGateway()
    gw._connected = False
    gw._ip_blocked = True
    gw._reconnect_interval_secs = 0.05
    calls: list[int] = []

    def _stub_reconnect():
        calls.append(1)

    with patch.object(gw, "_maybe_reconnect_disconnected", side_effect=_stub_reconnect):
        gw.start_reconnect_loop()
        await asyncio.sleep(0.15)
        gw.stop_reconnect_loop()
    assert calls == []


@pytest.mark.asyncio
async def test_stop_is_idempotent() -> None:
    """Calling ``stop_reconnect_loop`` twice must not raise."""
    gw = SinopacGateway()
    gw._connected = True
    gw._reconnect_interval_secs = 0.05
    gw.start_reconnect_loop()
    gw.stop_reconnect_loop()
    gw.stop_reconnect_loop()  # second call is a no-op
    # Restart should also be safe.
    gw.start_reconnect_loop()
    gw.stop_reconnect_loop()


@pytest.mark.asyncio
async def test_start_is_idempotent() -> None:
    """Calling ``start_reconnect_loop`` while already running must not double-spawn."""
    gw = SinopacGateway()
    gw._connected = True
    gw._reconnect_interval_secs = 0.05
    gw.start_reconnect_loop()
    first_task = gw._reconnect_task
    gw.start_reconnect_loop()
    assert gw._reconnect_task is first_task
    gw.stop_reconnect_loop()
