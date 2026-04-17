"""
tests/test_midi_handler.py – unit tests for MidiHandler.

mididings and jack are stubbed via sys.modules so no hardware is required.
"""

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

# ── Stubs ──────────────────────────────────────────────────────────────────────
jack_stub            = types.ModuleType("jack")
jack_stub.Client     = MagicMock()
jack_stub.JackError  = Exception
jack_stub.ROLLING    = 1
sys.modules.setdefault("jack", jack_stub)

def _make_mididings_stub():
    md          = types.ModuleType("mididings")
    md.CTRL     = 0xB0
    md.Call     = lambda fn: fn
    md.Filter   = lambda _: MagicMock(__rshift__=lambda s, o: MagicMock())
    md.config   = MagicMock()
    md.run      = MagicMock()
    engine_mod  = types.ModuleType("mididings.engine")
    engine_mod.output_event = MagicMock()
    event_mod   = types.ModuleType("mididings.event")
    event_mod.CtrlEvent = MagicMock(return_value=object())
    sys.modules["mididings.engine"] = engine_mod
    sys.modules["mididings.event"]  = event_mod
    sys.modules["mididings"]        = md
    return md

_mididings_stub = _make_mididings_stub()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import big_tempo.midi as midi_module
midi_module.HAS_MIDIDINGS = True

from big_tempo.midi import MidiHandler


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fake_event(ctrl: int, value: int):
    ev = MagicMock(); ev.ctrl = ctrl; ev.value = value
    return ev


def _make_handler(cfg: dict):
    received = []
    root = MagicMock()
    root.after = lambda delay, fn: fn()

    def on_receive(action, amount, raw, osc_spec=None, midi_spec=None):
        received.append({
            "action": action, "amount": amount, "raw": raw,
            "osc_spec": osc_spec, "midi_spec": midi_spec,
        })

    handler = MidiHandler(cfg, root, on_receive)
    handler._started.set()
    return handler, received


def _reset_engine():
    sys.modules["mididings.engine"].output_event.reset_mock()
    sys.modules["mididings.event"].CtrlEvent.reset_mock()


CFG_BASE = {
    "min_bpm": 20.0, "max_bpm": 300.0,
    "midi": {"client_name": "test", "channel": 1},
    "receive": {
        "CC20": {"action": "up",   "amount": 1.0},
        "CC21": {"action": "down", "amount": 2.5},
        "CC22": {"action": "set"},
    },
    "midi_send": {
        "on_change": {"cc": 30, "channel": 1},
    },
}


# ── _handle_ctrl dispatch ──────────────────────────────────────────────────────

class TestHandleCtrl:
    def test_up_dispatched(self):
        h, received = _make_handler(CFG_BASE)
        h._handle_ctrl(_fake_event(20, 64))
        assert received[0]["action"] == "up"
        assert received[0]["amount"] == 1.0

    def test_down_dispatched(self):
        h, received = _make_handler(CFG_BASE)
        h._handle_ctrl(_fake_event(21, 0))
        assert received[0]["action"] == "down"
        assert received[0]["amount"] == 2.5

    def test_set_dispatched(self):
        h, received = _make_handler(CFG_BASE)
        h._handle_ctrl(_fake_event(22, 100))
        assert received[0]["action"] == "set"
        assert received[0]["raw"]    == 100

    def test_unmapped_cc_ignored(self):
        h, received = _make_handler(CFG_BASE)
        h._handle_ctrl(_fake_event(99, 64))
        assert received == []

    def test_osc_spec_forwarded(self):
        cfg = {**CFG_BASE, "receive": {
            "CC20": {"action": "up", "amount": 1.0,
                     "osc_send": {"address": "/x", "args": ["bpm"]}},
        }}
        h, received = _make_handler(cfg)
        h._handle_ctrl(_fake_event(20, 0))
        assert received[0]["osc_spec"] == {"address": "/x", "args": ["bpm"]}

    def test_midi_spec_forwarded(self):
        cfg = {**CFG_BASE, "receive": {
            "CC20": {"action": "up", "amount": 1.0,
                     "midi_send": {"cc": 50, "channel": 2, "value": "raw"}},
        }}
        h, received = _make_handler(cfg)
        h._handle_ctrl(_fake_event(20, 77))
        assert received[0]["midi_spec"] == {"cc": 50, "channel": 2, "value": "raw"}

    def test_both_specs_none_when_absent(self):
        h, received = _make_handler(CFG_BASE)
        h._handle_ctrl(_fake_event(20, 0))
        assert received[0]["osc_spec"]  is None
        assert received[0]["midi_spec"] is None

    def test_multiple_events_accumulated(self):
        h, received = _make_handler(CFG_BASE)
        for ctrl in (20, 21, 22):
            h._handle_ctrl(_fake_event(ctrl, 0))
        assert len(received) == 3


# ── _resolve_value ─────────────────────────────────────────────────────────────

class TestResolveValue:
    def _h(self): return _make_handler(CFG_BASE)[0]

    def test_bpm_token_maps_to_midi(self):
        h = self._h()
        # 20 BPM = min → 0
        assert h._resolve_value("bpm", bpm=20.0, raw=0) == 0
        # 300 BPM = max → 127
        assert h._resolve_value("bpm", bpm=300.0, raw=0) == 127

    def test_raw_token_passes_through(self):
        h = self._h()
        assert h._resolve_value("raw", bpm=120.0, raw=77) == 77

    def test_raw_clamped_to_valid_range(self):
        h = self._h()
        assert h._resolve_value("raw", bpm=120.0, raw=200) == 127
        assert h._resolve_value("raw", bpm=120.0, raw=-5)  == 0

    def test_literal_int_used_directly(self):
        h = self._h()
        assert h._resolve_value(64, bpm=120.0, raw=0) == 64

    def test_literal_clamped_to_valid_range(self):
        h = self._h()
        assert h._resolve_value(200, bpm=120.0, raw=0) == 127
        assert h._resolve_value(-1,  bpm=120.0, raw=0) == 0

    def test_default_is_bpm(self):
        """send_with_context with no value key should default to bpm token."""
        _reset_engine()
        h = self._h()
        h.send_with_context({"cc": 30, "channel": 1}, bpm=20.0, raw=0)
        ctrl_mock = sys.modules["mididings.event"].CtrlEvent
        _, kwargs = ctrl_mock.call_args
        assert kwargs.get("value", ctrl_mock.call_args[0][3] if len(ctrl_mock.call_args[0]) > 3 else None) == 0


# ── send_with_context ──────────────────────────────────────────────────────────

class TestSendWithContext:
    def setup_method(self): _reset_engine()

    def test_fires_output_event(self):
        h = _make_handler(CFG_BASE)[0]
        h.send_with_context({"cc": 30, "channel": 1, "value": "bpm"},
                            bpm=20.0, raw=0)
        assert sys.modules["mididings.engine"].output_event.called

    def test_noop_before_engine_started(self):
        h = _make_handler(CFG_BASE)[0]
        h._started.clear()
        h.send_with_context({"cc": 30, "channel": 1}, bpm=120.0, raw=0)
        assert not sys.modules["mididings.engine"].output_event.called

    def test_channel_passed_to_ctrl_event(self):
        h = _make_handler(CFG_BASE)[0]
        ctrl_mock = sys.modules["mididings.event"].CtrlEvent
        h.send_with_context({"cc": 30, "channel": 3, "value": 64},
                            bpm=120.0, raw=0)
        _, kwargs = ctrl_mock.call_args
        assert kwargs.get("channel") == 3

    def test_literal_value_sent(self):
        h = _make_handler(CFG_BASE)[0]
        ctrl_mock = sys.modules["mididings.event"].CtrlEvent
        h.send_with_context({"cc": 30, "channel": 1, "value": 99},
                            bpm=120.0, raw=0)
        _, kwargs = ctrl_mock.call_args
        assert kwargs.get("value") == 99

    def test_raw_value_sent(self):
        h = _make_handler(CFG_BASE)[0]
        ctrl_mock = sys.modules["mididings.event"].CtrlEvent
        h.send_with_context({"cc": 30, "channel": 1, "value": "raw"},
                            bpm=120.0, raw=55)
        _, kwargs = ctrl_mock.call_args
        assert kwargs.get("value") == 55


# ── send_on_change ─────────────────────────────────────────────────────────────

class TestSendOnChange:
    def setup_method(self): _reset_engine()

    def test_fires_when_on_change_configured(self):
        h = _make_handler(CFG_BASE)[0]
        h.send_on_change(20.0)   # min BPM → value 0
        assert sys.modules["mididings.engine"].output_event.called

    def test_noop_when_on_change_absent(self):
        cfg = {**CFG_BASE, "midi_send": {}}
        h = _make_handler(cfg)[0]
        h.send_on_change(120.0)
        assert not sys.modules["mididings.engine"].output_event.called

    def test_send_bpm_alias_works(self):
        """send_bpm() must still work as an alias for send_on_change()."""
        h = _make_handler(CFG_BASE)[0]
        h.send_bpm(20.0)
        assert sys.modules["mididings.engine"].output_event.called


# ── No-mididings path ──────────────────────────────────────────────────────────

class TestNoMididings:
    def test_start_noop_and_warns(self, capsys):
        orig = midi_module.HAS_MIDIDINGS
        try:
            midi_module.HAS_MIDIDINGS = False
            h = _make_handler(CFG_BASE)[0]
            h.start()
            assert "disabled" in capsys.readouterr().err.lower()
        finally:
            midi_module.HAS_MIDIDINGS = orig
