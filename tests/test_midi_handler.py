"""
tests/test_midi_handler.py – unit tests for MidiHandler.

mididings and jack are not available in the test environment, so they are
stubbed out via sys.modules before importing the package.  This lets us test
the CC routing / dispatch logic without hardware or a running JACK server.
"""

import os
import sys
import types
import threading
from unittest.mock import MagicMock, call, patch

import pytest

# ── Stub out optional C‑extension modules before any package import ────────────
# jack stub
jack_stub = types.ModuleType("jack")
jack_stub.Client     = MagicMock()
jack_stub.JackError  = Exception
jack_stub.ROLLING    = 1
sys.modules.setdefault("jack", jack_stub)

# mididings stub (top‑level module + sub‑modules referenced inside MidiHandler)
def _make_mididings_stub():
    md = types.ModuleType("mididings")
    md.CTRL   = 0xB0
    md.Call   = lambda fn: fn
    md.Filter = lambda _: MagicMock(__rshift__=lambda s, o: MagicMock())
    md.config = MagicMock()
    md.run    = MagicMock()

    engine_mod = types.ModuleType("mididings.engine")
    engine_mod.output_event = MagicMock()
    sys.modules["mididings.engine"] = engine_mod

    event_mod  = types.ModuleType("mididings.event")
    event_mod.CtrlEvent = MagicMock(return_value=object())
    sys.modules["mididings.event"] = event_mod

    sys.modules["mididings"] = md
    return md

_mididings_stub = _make_mididings_stub()

# ── Now safe to import our package ────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import big_tempo.midi as midi_module
# Patch HAS_MIDIDINGS so the handler believes the library is present
midi_module.HAS_MIDIDINGS = True

from big_tempo.midi import MidiHandler


# ── Helpers ────────────────────────────────────────────────────────────────────
def _fake_event(ctrl: int, value: int):
    """Return a minimal object that looks like a mididings CtrlEvent."""
    ev = MagicMock()
    ev.ctrl  = ctrl
    ev.value = value
    return ev


def _make_handler(cfg: dict):
    """
    Create a MidiHandler with a fake tkinter root and a recording callback.

    The fake root captures ``after(delay, fn)`` calls and executes them
    immediately (delay=0 path) so tests run synchronously.
    """
    received: list = []

    root = MagicMock()
    # root.after(0, fn) should execute fn() immediately
    root.after = lambda delay, fn: fn()

    def on_receive(action, amount, raw):
        received.append({"action": action, "amount": amount, "raw": raw})

    handler          = MidiHandler(cfg, root, on_receive)
    handler._started.set()   # skip the real mididings startup
    return handler, received


# ── Tests ──────────────────────────────────────────────────────────────────────
CFG_BASE = {
    "min_bpm": 20.0,
    "max_bpm": 300.0,
    "midi": {"client_name": "test", "channel": 1},
    "receive": {
        "CC20": {"action": "up",   "amount": 1.0},
        "CC21": {"action": "down", "amount": 2.5},
        "CC22": {"action": "set"},
    },
    "send": {
        "on_change": {"cc": 30, "channel": 1},
    },
}


class TestHandleCtrl:
    """_handle_ctrl() should dispatch the correct action for each CC mapping."""

    def test_up_action_dispatched(self):
        handler, received = _make_handler(CFG_BASE)
        handler._handle_ctrl(_fake_event(20, 64))
        assert len(received) == 1
        assert received[0]["action"] == "up"
        assert received[0]["amount"] == 1.0

    def test_down_action_dispatched(self):
        handler, received = _make_handler(CFG_BASE)
        handler._handle_ctrl(_fake_event(21, 0))
        assert received[0]["action"] == "down"
        assert received[0]["amount"] == 2.5

    def test_set_action_dispatched(self):
        handler, received = _make_handler(CFG_BASE)
        handler._handle_ctrl(_fake_event(22, 100))
        assert received[0]["action"] == "set"
        assert received[0]["raw"]    == 100

    def test_unmapped_cc_ignored(self):
        handler, received = _make_handler(CFG_BASE)
        handler._handle_ctrl(_fake_event(99, 64))   # CC99 not in config
        assert received == []

    def test_raw_value_forwarded_correctly(self):
        handler, received = _make_handler(CFG_BASE)
        handler._handle_ctrl(_fake_event(20, 77))
        assert received[0]["raw"] == 77

    def test_multiple_events_accumulated(self):
        handler, received = _make_handler(CFG_BASE)
        handler._handle_ctrl(_fake_event(20, 1))
        handler._handle_ctrl(_fake_event(21, 2))
        handler._handle_ctrl(_fake_event(22, 3))
        assert len(received) == 3
        assert [r["action"] for r in received] == ["up", "down", "set"]


class TestSendBpm:
    """send_bpm() should call engine.output_event with the right CC value."""

    def test_send_calls_output_event(self):
        handler, _ = _make_handler(CFG_BASE)
        engine_mock = sys.modules["mididings.engine"]
        engine_mock.output_event.reset_mock()

        handler.send_bpm(20.0)  # min BPM → value 0
        assert engine_mock.output_event.called

    def test_no_send_when_on_change_absent(self):
        cfg = {**CFG_BASE, "send": {}}
        handler, _ = _make_handler(cfg)
        engine_mock = sys.modules["mididings.engine"]
        engine_mock.output_event.reset_mock()

        handler.send_bpm(120.0)
        assert not engine_mock.output_event.called

    def test_no_send_before_engine_started(self):
        handler, _ = _make_handler(CFG_BASE)
        handler._started.clear()   # pretend engine not yet ready
        engine_mock = sys.modules["mididings.engine"]
        engine_mock.output_event.reset_mock()

        handler.send_bpm(120.0)
        assert not engine_mock.output_event.called

    def test_ctrl_event_created_with_correct_channel(self):
        cfg = {**CFG_BASE, "send": {"on_change": {"cc": 42, "channel": 3}}}
        handler, _ = _make_handler(cfg)
        ctrl_mock = sys.modules["mididings.event"].CtrlEvent
        ctrl_mock.reset_mock()

        handler.send_bpm(120.0)
        args, kwargs = ctrl_mock.call_args
        # channel kwarg (or positional) must match config
        channel_used = kwargs.get("channel", args[1] if len(args) > 1 else None)
        assert channel_used == 3


class TestStartNoMididings:
    """When HAS_MIDIDINGS is False, start() should be a silent no‑op."""

    def test_start_noop_without_mididings(self, capsys):
        original = midi_module.HAS_MIDIDINGS
        try:
            midi_module.HAS_MIDIDINGS = False
            handler, _ = _make_handler(CFG_BASE)
            handler.start()           # must not raise
            captured = capsys.readouterr()
            assert "disabled" in captured.err.lower()
        finally:
            midi_module.HAS_MIDIDINGS = original
