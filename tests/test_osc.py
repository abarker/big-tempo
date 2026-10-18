"""
tests/test_osc.py – unit tests for the pool-based OscSender.

python-osc is stubbed via sys.modules so no network activity occurs.
"""

import os
import sys
import types
from unittest.mock import MagicMock, call

import pytest

# ── Stub out pythonosc before importing the module ─────────────────────────────
def _make_client_mock():
    m = MagicMock()
    m.send_message = MagicMock()
    return m

_MockSimpleUDPClient = MagicMock(side_effect=lambda h, p: _make_client_mock())

_pythonosc_stub = types.ModuleType("pythonosc")
_udp_stub       = types.ModuleType("pythonosc.udp_client")
_udp_stub.SimpleUDPClient = _MockSimpleUDPClient
sys.modules.setdefault("pythonosc",            _pythonosc_stub)
sys.modules.setdefault("pythonosc.udp_client", _udp_stub)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import big_tempo.osc as osc_module
osc_module.HAS_OSC = True

from big_tempo.osc import OscSender


# ── Helpers ────────────────────────────────────────────────────────────────────

def _reset():
    _MockSimpleUDPClient.reset_mock()
    _MockSimpleUDPClient.side_effect = lambda h, p: _make_client_mock()


def _spec(host="127.0.0.1", port=9000, address="/x", args=None):
    """Build a minimal OSC action spec."""
    s = {"send": "OSC", "host": host, "port": port, "address": address}
    if args is not None:
        s["args"] = args
    return s


# ── Construction ───────────────────────────────────────────────────────────────

class TestConstruction:
    def test_enabled_when_has_osc(self):
        assert OscSender({}).enabled is True

    def test_disabled_when_no_library(self):
        orig = osc_module.HAS_OSC
        try:
            osc_module.HAS_OSC = False
            assert not OscSender({}).enabled
        finally:
            osc_module.HAS_OSC = orig

    def test_no_library_prints_warning(self, capsys):
        orig = osc_module.HAS_OSC
        try:
            osc_module.HAS_OSC = False
            OscSender({})
            assert "python-osc" in capsys.readouterr().err
        finally:
            osc_module.HAS_OSC = orig

    def test_no_clients_created_at_construction(self):
        """Pool is lazy – no sockets opened until first send."""
        _reset()
        OscSender({})
        _MockSimpleUDPClient.assert_not_called()


# ── Pool behavior ─────────────────────────────────────────────────────────────

class TestPool:
    def setup_method(self): _reset()

    def test_client_created_on_first_send(self):
        s = OscSender({})
        s.send_with_context(_spec(), bpm=120.0, raw=0)
        _MockSimpleUDPClient.assert_called_once_with("127.0.0.1", 9000)

    def test_client_reused_on_repeated_sends(self):
        s = OscSender({})
        s.send_with_context(_spec(), bpm=120.0, raw=0)
        s.send_with_context(_spec(), bpm=130.0, raw=0)
        _MockSimpleUDPClient.assert_called_once()   # only one socket

    def test_separate_clients_for_different_targets(self):
        s = OscSender({})
        s.send_with_context(_spec(host="127.0.0.1", port=9000), bpm=120.0, raw=0)
        s.send_with_context(_spec(host="10.0.0.5",  port=7400), bpm=120.0, raw=0)
        assert _MockSimpleUDPClient.call_count == 2
        calls = _MockSimpleUDPClient.call_args_list
        assert call("127.0.0.1", 9000) in calls
        assert call("10.0.0.5",  7400) in calls

    def test_same_host_different_port_makes_two_clients(self):
        s = OscSender({})
        s.send_with_context(_spec(port=9000), bpm=120.0, raw=0)
        s.send_with_context(_spec(port=9001), bpm=120.0, raw=0)
        assert _MockSimpleUDPClient.call_count == 2

    def test_client_creation_failure_warns(self, capsys):
        _reset()
        _MockSimpleUDPClient.side_effect = OSError("refused")
        try:
            s = OscSender({})
            s.send_with_context(_spec(), bpm=120.0, raw=0)
            assert "Warning" in capsys.readouterr().err
        finally:
            _MockSimpleUDPClient.side_effect = lambda h, p: _make_client_mock()
            _reset()

    def test_failed_client_does_not_retry(self, capsys):
        """A failed (host, port) must not call SimpleUDPClient again."""
        _reset()
        _MockSimpleUDPClient.side_effect = OSError("refused")
        try:
            s = OscSender({})
            s.send_with_context(_spec(), bpm=120.0, raw=0)
            s.send_with_context(_spec(), bpm=120.0, raw=0)
            assert _MockSimpleUDPClient.call_count == 1
        finally:
            _MockSimpleUDPClient.side_effect = lambda h, p: _make_client_mock()
            _reset()


# ── _resolve_args ──────────────────────────────────────────────────────────────

class TestResolveArgs:
    def setup_method(self): _reset()

    def _sender(self): return OscSender({})

    def test_bpm_token_substituted(self):
        assert self._sender()._resolve_args(["bpm"], bpm=130.0, raw=64) == [130.0]

    def test_raw_token_substituted(self):
        assert self._sender()._resolve_args(["raw"], bpm=130.0, raw=64) == [64]

    def test_rolling_token_substituted(self):
        assert self._sender()._resolve_args(["rolling"], bpm=120.0, raw=0, rolling=1) == [1]

    def test_rolling_defaults_to_zero(self):
        assert self._sender()._resolve_args(["rolling"], bpm=120.0, raw=0) == [0]

    def test_literal_int_passed_through(self):
        assert self._sender()._resolve_args([42], bpm=130.0, raw=0) == [42]

    def test_literal_float_passed_through(self):
        assert self._sender()._resolve_args([1.5], bpm=130.0, raw=0) == [1.5]

    def test_literal_string_passed_through(self):
        assert self._sender()._resolve_args(["hello"], bpm=130.0, raw=0) == ["hello"]

    def test_mixed_tokens_and_literals(self):
        result = self._sender()._resolve_args(["bpm", "raw", 99], bpm=120.0, raw=10)
        assert result == [120.0, 10, 99]

    def test_empty_args_returns_empty(self):
        assert self._sender()._resolve_args([], bpm=120.0, raw=0) == []

    def test_bpm_returned_as_float(self):
        result = self._sender()._resolve_args(["bpm"], bpm=120, raw=0)
        assert isinstance(result[0], float)

    def test_raw_returned_as_int(self):
        result = self._sender()._resolve_args(["raw"], bpm=120.0, raw=64.9)
        assert isinstance(result[0], int)


# ── send_with_context ──────────────────────────────────────────────────────────

class TestSendWithContext:
    def setup_method(self): _reset()

    def test_correct_address_and_bpm(self):
        s = OscSender({})
        s.send_with_context(
            {"host": "127.0.0.1", "port": 9000,
             "address": "/Hydrogen/BPM", "args": ["bpm"]},
            bpm=130.0, raw=0,
        )
        client = s._pool[("127.0.0.1", 9000)]
        client.send_message.assert_called_once_with("/Hydrogen/BPM", 130.0)

    def test_raw_token_resolved(self):
        s = OscSender({})
        s.send_with_context(
            {"host": "127.0.0.1", "port": 9000, "address": "/foo", "args": ["raw"]},
            bpm=120.0, raw=77,
        )
        client = s._pool[("127.0.0.1", 9000)]
        client.send_message.assert_called_once_with("/foo", 77)

    def test_no_args_sends_none(self):
        s = OscSender({})
        s.send_with_context(
            {"host": "127.0.0.1", "port": 9000, "address": "/Hydrogen/PLAY"},
            bpm=120.0, raw=0,
        )
        client = s._pool[("127.0.0.1", 9000)]
        client.send_message.assert_called_once_with("/Hydrogen/PLAY", None)

    def test_multiple_args_sent_as_list(self):
        s = OscSender({})
        s.send_with_context(
            {"host": "127.0.0.1", "port": 9000, "address": "/a",
             "args": ["bpm", "raw"]},
            bpm=120.0, raw=64,
        )
        client = s._pool[("127.0.0.1", 9000)]
        client.send_message.assert_called_once_with("/a", [120.0, 64])

    def test_literal_args_passed_unchanged(self):
        s = OscSender({})
        s.send_with_context(
            {"host": "127.0.0.1", "port": 9000, "address": "/b",
             "args": [1, "hello", True]},
            bpm=120.0, raw=0,
        )
        client = s._pool[("127.0.0.1", 9000)]
        client.send_message.assert_called_once_with("/b", [1, "hello", True])

    def test_noop_when_library_absent(self):
        orig = osc_module.HAS_OSC
        try:
            osc_module.HAS_OSC = False
            s = OscSender({})
            s.send_with_context(_spec(address="/x"), bpm=120.0, raw=0)
            _MockSimpleUDPClient.assert_not_called()
        finally:
            osc_module.HAS_OSC = orig

    def test_send_error_warns_once(self, capsys):
        s = OscSender({})
        # Prime the pool with a client whose send_message always fails
        bad_client = MagicMock()
        bad_client.send_message.side_effect = OSError("refused")
        s._pool[("127.0.0.1", 9000)] = bad_client
        for _ in range(3):
            s.send_with_context(_spec(address="/x", args=["bpm"]), bpm=120.0, raw=0)
        assert capsys.readouterr().err.count("OSC send error") == 1

    def test_defaults_used_when_host_port_absent(self):
        """Spec with no host/port falls back to DEFAULT_HOST/DEFAULT_PORT."""
        s = OscSender({})
        s.send_with_context({"address": "/x"}, bpm=120.0, raw=0)
        assert ("127.0.0.1", 9000) in s._pool

    def test_two_targets_receive_independent_messages(self):
        s = OscSender({})
        s.send_with_context(
            {"host": "127.0.0.1", "port": 9000, "address": "/local"},
            bpm=120.0, raw=0,
        )
        s.send_with_context(
            {"host": "10.0.0.5", "port": 7400, "address": "/remote"},
            bpm=120.0, raw=0,
        )
        client_a = s._pool[("127.0.0.1", 9000)]
        client_b = s._pool[("10.0.0.5",  7400)]
        client_a.send_message.assert_called_once_with("/local",  None)
        client_b.send_message.assert_called_once_with("/remote", None)
