"""
tests/test_osc.py – unit tests for the generalised OscSender.

python-osc is stubbed via sys.modules so no network activity occurs.
"""

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

# ── Stub out pythonosc before importing the module ─────────────────────────────
_mock_client_instance = MagicMock()
_mock_client_instance.send_message = MagicMock()
_MockSimpleUDPClient  = MagicMock(return_value=_mock_client_instance)

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
    _MockSimpleUDPClient.return_value = _mock_client_instance
    _mock_client_instance.reset_mock()
    _mock_client_instance.send_message = MagicMock()


def _cfg(host="127.0.0.1", port=9000, osc_send=None, receive=None):
    c = {
        "min_bpm": 20.0, "max_bpm": 300.0,
        "osc": {"host": host, "port": port},
    }
    if osc_send: c["osc_send"] = osc_send
    if receive:  c["receive"]  = receive
    return c


# ── Construction ───────────────────────────────────────────────────────────────

class TestConstruction:
    def test_enabled_when_osc_section_present(self):
        _reset()
        assert OscSender(_cfg()).enabled

    def test_disabled_when_osc_section_absent(self):
        _reset()
        assert not OscSender({"min_bpm": 20.0, "max_bpm": 300.0}).enabled

    def test_client_created_with_correct_host_and_port(self):
        _reset()
        OscSender(_cfg(host="10.0.0.1", port=8000))
        _MockSimpleUDPClient.assert_called_once_with("10.0.0.1", 8000)

    def test_default_host_and_port(self):
        _reset()
        OscSender({"osc": {}})
        args, _ = _MockSimpleUDPClient.call_args
        assert args == ("127.0.0.1", 9000)

    def test_no_library_prints_warning(self, capsys):
        orig = osc_module.HAS_OSC
        try:
            osc_module.HAS_OSC = False
            s = OscSender(_cfg())
            assert not s.enabled
            assert "python-osc" in capsys.readouterr().err
        finally:
            osc_module.HAS_OSC = orig

    def test_client_error_prints_warning(self, capsys):
        _reset()
        _MockSimpleUDPClient.side_effect = OSError("refused")
        try:
            s = OscSender(_cfg())
            assert not s.enabled
            assert "Warning" in capsys.readouterr().err
        finally:
            _MockSimpleUDPClient.side_effect = None
            _reset()


# ── _resolve_args ──────────────────────────────────────────────────────────────

class TestResolveArgs:
    def setup_method(self): _reset()

    def _sender(self): return OscSender(_cfg())

    def test_bpm_token_substituted(self):
        s = self._sender()
        assert s._resolve_args(["bpm"], bpm=130.0, raw=64) == [130.0]

    def test_raw_token_substituted(self):
        s = self._sender()
        assert s._resolve_args(["raw"], bpm=130.0, raw=64) == [64]

    def test_literal_int_passed_through(self):
        s = self._sender()
        assert s._resolve_args([42], bpm=130.0, raw=0) == [42]

    def test_literal_float_passed_through(self):
        s = self._sender()
        assert s._resolve_args([1.5], bpm=130.0, raw=0) == [1.5]

    def test_literal_string_passed_through(self):
        s = self._sender()
        assert s._resolve_args(["hello"], bpm=130.0, raw=0) == ["hello"]

    def test_mixed_tokens_and_literals(self):
        s = self._sender()
        result = s._resolve_args(["bpm", "raw", 99], bpm=120.0, raw=10)
        assert result == [120.0, 10, 99]

    def test_empty_args_returns_empty(self):
        s = self._sender()
        assert s._resolve_args([], bpm=120.0, raw=0) == []

    def test_bpm_returned_as_float(self):
        s = self._sender()
        result = s._resolve_args(["bpm"], bpm=120, raw=0)  # int input
        assert isinstance(result[0], float)

    def test_raw_returned_as_int(self):
        s = self._sender()
        result = s._resolve_args(["raw"], bpm=120.0, raw=64.9)  # float input
        assert isinstance(result[0], int)


# ── send_with_context ──────────────────────────────────────────────────────────

class TestSendWithContext:
    def setup_method(self): _reset()

    def test_correct_address_and_bpm(self):
        s = OscSender(_cfg())
        s.send_with_context({"address": "/Hydrogen/BPM", "args": ["bpm"]},
                            bpm=130.0, raw=0)
        _mock_client_instance.send_message.assert_called_once_with(
            "/Hydrogen/BPM", 130.0
        )

    def test_raw_token_resolved(self):
        s = OscSender(_cfg())
        s.send_with_context({"address": "/foo", "args": ["raw"]},
                            bpm=120.0, raw=77)
        _mock_client_instance.send_message.assert_called_once_with("/foo", 77)

    def test_no_args_sends_none(self):
        s = OscSender(_cfg())
        s.send_with_context({"address": "/Hydrogen/PLAY"}, bpm=120.0, raw=0)
        _mock_client_instance.send_message.assert_called_once_with(
            "/Hydrogen/PLAY", None
        )

    def test_multiple_args_sent_as_list(self):
        s = OscSender(_cfg())
        s.send_with_context({"address": "/a", "args": ["bpm", "raw"]},
                            bpm=120.0, raw=64)
        _mock_client_instance.send_message.assert_called_once_with(
            "/a", [120.0, 64]
        )

    def test_literal_args_passed_unchanged(self):
        s = OscSender(_cfg())
        s.send_with_context({"address": "/b", "args": [1, "hello", True]},
                            bpm=120.0, raw=0)
        _mock_client_instance.send_message.assert_called_once_with(
            "/b", [1, "hello", True]
        )

    def test_noop_when_disabled(self):
        _reset()
        s = OscSender({"min_bpm": 20.0})   # no osc section
        s.send_with_context({"address": "/x"}, bpm=120.0, raw=0)
        _mock_client_instance.send_message.assert_not_called()

    def test_send_error_warns_once(self, capsys):
        s = OscSender(_cfg())
        _mock_client_instance.send_message.side_effect = OSError("refused")
        try:
            for _ in range(3):
                s.send_with_context({"address": "/x", "args": ["bpm"]},
                                    bpm=120.0, raw=0)
            assert capsys.readouterr().err.count("OSC send error") == 1
        finally:
            _mock_client_instance.send_message.side_effect = None


# ── send_on_change ─────────────────────────────────────────────────────────────

class TestSendOnChange:
    def setup_method(self): _reset()

    def test_fires_when_on_change_configured(self):
        cfg = _cfg(osc_send={"on_change": {"address": "/Hydrogen/BPM",
                                            "args": ["bpm"]}})
        s = OscSender(cfg)
        s.send_on_change(120.0)
        _mock_client_instance.send_message.assert_called_once_with(
            "/Hydrogen/BPM", 120.0
        )

    def test_noop_when_on_change_absent(self):
        s = OscSender(_cfg())   # no osc_send section
        s.send_on_change(120.0)
        _mock_client_instance.send_message.assert_not_called()

    def test_multiple_calls_send_each_time(self):
        cfg = _cfg(osc_send={"on_change": {"address": "/H/BPM", "args": ["bpm"]}})
        s = OscSender(cfg)
        s.send_on_change(100.0)
        s.send_on_change(120.0)
        s.send_on_change(140.0)
        assert _mock_client_instance.send_message.call_count == 3

    def test_custom_address_respected(self):
        cfg = _cfg(osc_send={"on_change": {"address": "/MyApp/tempo",
                                            "args": ["bpm"]}})
        s = OscSender(cfg)
        s.send_on_change(90.0)
        addr = _mock_client_instance.send_message.call_args[0][0]
        assert addr == "/MyApp/tempo"
