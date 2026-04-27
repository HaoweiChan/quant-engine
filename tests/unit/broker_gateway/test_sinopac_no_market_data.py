"""Pin the post-refactor contract: SinopacGateway is trading-only.

After the credential refactor, the Sinopac trading gateway no longer
subscribes ticks. Tick subscription is owned exclusively by the
standalone subscriber in ``src.api.helpers._start_market_data_subscriber``,
which logs in with the group-level data-only API key/secret pair.

These tests would have caught a regression where someone re-introduces
``_subscribe_market_data`` (or ``_live_bar_store``) into the gateway —
which would mean per-account trading credentials silently end up with
data-feed permissions and a separate shioaji subscription burden.
"""
from __future__ import annotations

import inspect

from src.broker_gateway.sinopac import SinopacGateway


def test_gateway_does_not_carry_a_private_bar_store():
    """The gateway must not own a ``_live_bar_store`` — that lives on
    the helpers.py-level shared store now."""
    gw = SinopacGateway()
    assert not hasattr(gw, "_live_bar_store"), (
        "SinopacGateway must not own a private bar store; the data feed "
        "is fed by helpers._start_market_data_subscriber into the shared "
        "LiveMinuteBarStore created in _init_war_room."
    )


def test_gateway_does_not_define_subscribe_market_data():
    """No method on the gateway should subscribe ticks — the feed is
    owned exclusively by the standalone helpers.py subscriber."""
    gw = SinopacGateway()
    assert not hasattr(gw, "_subscribe_market_data"), (
        "SinopacGateway must not define _subscribe_market_data — that "
        "method belongs only on the data-feed path in helpers.py."
    )


def test_gateway_does_not_track_subscribed_contracts():
    """The module-level ``_SUBSCRIBED_CONTRACTS`` global was the way the
    old code dedup'd tick subscriptions across multiple gateway instances.
    With the trading gateway out of the data path, that global must not
    exist either."""
    import src.broker_gateway.sinopac as sj_module
    assert not hasattr(sj_module, "_SUBSCRIBED_CONTRACTS"), (
        "module-level _SUBSCRIBED_CONTRACTS must not exist — the trading "
        "gateway no longer subscribes ticks."
    )


def test_connect_signature_does_not_call_subscribe():
    """Belt-and-braces: even if someone re-adds the helpers.py-style
    subscribe method later, the gateway's ``connect`` must not call
    anything starting with ``_subscribe_``. We inspect the source rather
    than runtime-trace because connect() does network IO we can't run
    in a unit test."""
    src = inspect.getsource(SinopacGateway.connect)
    assert "_subscribe_market_data" not in src, (
        "SinopacGateway.connect must not invoke a subscription path. "
        "Tick subscription belongs in helpers._start_market_data_subscriber."
    )


def test_connect_does_not_fallback_to_data_only_group_creds():
    """The trading gateway must NOT silently fall back to the group-level
    SINOPAC_API_KEY / SINOPAC_API_SECRET pair — those have only 行情
    permission and would log in fine but reject every order. The
    fail-fast behaviour: refuse to connect when per-account creds are
    missing, surfacing the misconfig at startup instead of at order time."""
    src = inspect.getsource(SinopacGateway.connect)
    # The old fallback used to fetch the group via secret-manager.get_group("sinopac").
    assert 'get_group("sinopac")' not in src and "get_group('sinopac')" not in src, (
        "SinopacGateway.connect must not consult the group-level [sinopac] "
        "credentials — those are data-only and cannot place orders."
    )
    assert "group_fallback" not in src, (
        "SinopacGateway.connect must not register a group_fallback "
        "credential candidate."
    )


def test_connect_sets_clear_error_when_no_account_creds(monkeypatch):
    """Behavioural check: with an account id but no per-account creds in
    GSM, connect() must record a descriptive error and stay disconnected."""
    monkeypatch.setattr(
        "src.broker_gateway.registry.load_credentials",
        lambda _aid: {},
    )
    gw = SinopacGateway()
    gw.connect(account_id="never-onboarded")
    assert gw.is_connected is False
    err = gw._connect_error or ""
    assert "never-onboarded" in err
    assert "API_KEY" in err  # references the expected GSM key name
