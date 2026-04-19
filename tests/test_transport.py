"""
tests/test_transport.py – tests for transport event sends and the "rolling" token.

Tests:
  - OscSender._resolve_args  "rolling" token
  - MidiHandler._resolve_value "rolling" token
  - _on_transport_change dispatch logic (replicated inline; no tkinter needed)

No display, JACK, or mididings required.
"""

import os
import sys
import types
from unittest.mock import MagicMock, call

import pytest

# ── Stubs for optional C-extension modules ─────────────────────────────────────
jack_stub           = types.ModuleType("jack")
jack_stub.Client    = MagicMock()
jack_stub.JackError = Exception
jack_stub.ROLLING   = 1
sys.modules.setdefault("jack", jack_stub)

_md = types.ModuleType("mididings")
_md.CTRL = 0xB0; _md.Call = lambda f: f
_md.Filter = lambda _: MagicMock(__rshift__=lambda s, o: MagicMock())
_md.config = MagicMock(); _md.run = MagicMock()
sys.modules.setdefault("mididings", _md)
sys.modules.setdefault("mididings.engine", types.ModuleType("mididings.engine"))
sys.modules.setdefault("mididings.event",  types.ModuleType("mididings.event"))

_pt = types.ModuleType("pythonosc")
_pu = types.ModuleType("pythonosc.udp_client")
_pu.SimpleUDPClient = MagicMock(return_value=MagicMock())
sys.modules.setdefault("pythonosc",            _pt)
sys.modules.setdefault("pythonosc.udp_client", _pu)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import big_tempo.osc  as osc_module
import big_tempo.midi as midi_module
osc_module.HAS_OSC        = True
midi_module.HAS_MIDIDINGS = True

from big_tempo.osc  import OscSender
from big_tempo.midi import MidiHandler


# ── Helpers ────────────────────────────────────────────────────────────────────

def _osc_sender(cfg: dict) -> OscSender:
    return OscSender(cfg)


def _midi_handler(cfg: dict):
    received = []
    root = MagicMock()
    root.after = lambda d, f: f()
    def on_receive(*a, **kw): received.append(a)
    h = MidiHandler(cfg, root, on_receive)
    h._started.set()
    return h, received


def _on_transport_change(cfg: dict, midi_mock, osc_mock, rolling: bool,
                         current_bpm: float = 120.0) -> None:
    """
    Standalone reimplementation of BigTempo._on_transport_change,
    allowing tests to run without importing tkinter.
    """
    rolling_int = 1 if rolling else 0
    direction   = "transport_start" if rolling else "transport_stop"

    for trigger in (direction, "transport_toggle"):
        midi_spec = cfg.get("midi_send", {}).get(trigger)
        if midi_spec:
            midi_mock.send_with_context(
                midi_spec, bpm=current_bpm, raw=0, rolling=rolling_int
            )
        osc_spec = cfg.get("osc_send", {}).get(trigger)
        if osc_spec:
            osc_mock.send_with_context(
                osc_spec, bpm=current_bpm, raw=0, rolling=rolling_int
            )


# ── rolling token – OscSender._resolve_args ────────────────────────────────────

class TestOscRollingToken:
    def _sender(self):
        return OscSender({"osc": {"host": "127.0.0.1", "port": 9000}})

    def test_rolling_1_when_started(self):
        s = self._sender()
        assert s._resolve_args(["rolling"], bpm=120.0, raw=0, rolling=1) == [1]

    def test_rolling_0_when_stopped(self):
        s = self._sender()
        assert s._resolve_args(["rolling"], bpm=120.0, raw=0, rolling=0) == [0]

    def test_rolling_is_int(self):
        s = self._sender()
        result = s._resolve_args(["rolling"], bpm=120.0, raw=0, rolling=1)
        assert isinstance(result[0], int)

    def test_rolling_alongside_bpm(self):
        s = self._sender()
        result = s._resolve_args(["bpm", "rolling"], bpm=130.0, raw=0, rolling=1)
        assert result == [130.0, 1]

    def test_rolling_defaults_to_0(self):
        s = self._sender()
        assert s._resolve_args(["rolling"], bpm=120.0, raw=0) == [0]


# ── rolling token – MidiHandler._resolve_value ────────────────────────────────

class TestMidiRollingToken:
    CFG = {"min_bpm": 20.0, "max_bpm": 300.0, "midi_send": {}}

    def _h(self):
        return _midi_handler(self.CFG)[0]

    def test_rolling_1_gives_127(self):
        assert self._h()._resolve_value("rolling", bpm=120.0, raw=0, rolling=1) == 127

    def test_rolling_0_gives_0(self):
        assert self._h()._resolve_value("rolling", bpm=120.0, raw=0, rolling=0) == 0

    def test_rolling_default_is_0(self):
        assert self._h()._resolve_value("rolling", bpm=120.0, raw=0) == 0


# ── _on_transport_change dispatch ─────────────────────────────────────────────

class TestOnTransportChange:

    def _mocks(self):
        return MagicMock(), MagicMock()   # midi_mock, osc_mock

    # ── transport_start ────────────────────────────────────────────────────────

    def test_start_fires_transport_start_midi(self):
        cfg = {"midi_send": {"transport_start": {"cc": 31, "channel": 1, "value": 127}},
               "osc_send": {}}
        midi, osc = self._mocks()
        _on_transport_change(cfg, midi, osc, rolling=True)
        midi.send_with_context.assert_called_once_with(
            {"cc": 31, "channel": 1, "value": 127},
            bpm=120.0, raw=0, rolling=1,
        )

    def test_start_fires_transport_start_osc(self):
        cfg = {"midi_send": {},
               "osc_send": {"transport_start": {"address": "/H/PLAY", "args": []}}}
        midi, osc = self._mocks()
        _on_transport_change(cfg, midi, osc, rolling=True)
        osc.send_with_context.assert_called_once_with(
            {"address": "/H/PLAY", "args": []},
            bpm=120.0, raw=0, rolling=1,
        )

    def test_start_passes_current_bpm(self):
        cfg = {"midi_send": {"transport_start": {"cc": 31, "channel": 1, "value": 127}},
               "osc_send": {}}
        midi, osc = self._mocks()
        _on_transport_change(cfg, midi, osc, rolling=True, current_bpm=142.0)
        _, kwargs = midi.send_with_context.call_args
        assert kwargs["bpm"] == 142.0

    # ── transport_stop ─────────────────────────────────────────────────────────

    def test_stop_fires_transport_stop_midi(self):
        cfg = {"midi_send": {"transport_stop": {"cc": 31, "channel": 1, "value": 0}},
               "osc_send": {}}
        midi, osc = self._mocks()
        _on_transport_change(cfg, midi, osc, rolling=False)
        midi.send_with_context.assert_called_once_with(
            {"cc": 31, "channel": 1, "value": 0},
            bpm=120.0, raw=0, rolling=0,
        )

    def test_stop_does_not_fire_transport_start(self):
        cfg = {"midi_send": {"transport_start": {"cc": 31, "channel": 1, "value": 127}},
               "osc_send": {}}
        midi, osc = self._mocks()
        _on_transport_change(cfg, midi, osc, rolling=False)
        midi.send_with_context.assert_not_called()

    def test_start_does_not_fire_transport_stop(self):
        cfg = {"midi_send": {"transport_stop": {"cc": 31, "channel": 1, "value": 0}},
               "osc_send": {}}
        midi, osc = self._mocks()
        _on_transport_change(cfg, midi, osc, rolling=True)
        midi.send_with_context.assert_not_called()

    # ── transport_toggle ───────────────────────────────────────────────────────

    def test_toggle_fires_on_start(self):
        cfg = {"midi_send": {"transport_toggle": {"cc": 32, "channel": 1, "value": "rolling"}},
               "osc_send": {}}
        midi, osc = self._mocks()
        _on_transport_change(cfg, midi, osc, rolling=True)
        midi.send_with_context.assert_called_once_with(
            {"cc": 32, "channel": 1, "value": "rolling"},
            bpm=120.0, raw=0, rolling=1,
        )

    def test_toggle_fires_on_stop(self):
        cfg = {"midi_send": {"transport_toggle": {"cc": 32, "channel": 1, "value": "rolling"}},
               "osc_send": {}}
        midi, osc = self._mocks()
        _on_transport_change(cfg, midi, osc, rolling=False)
        midi.send_with_context.assert_called_once_with(
            {"cc": 32, "channel": 1, "value": "rolling"},
            bpm=120.0, raw=0, rolling=0,
        )

    def test_both_specific_and_toggle_fire_on_start(self):
        cfg = {
            "midi_send": {
                "transport_start":  {"cc": 31, "channel": 1, "value": 127},
                "transport_toggle": {"cc": 32, "channel": 1, "value": "rolling"},
            },
            "osc_send": {},
        }
        midi, osc = self._mocks()
        _on_transport_change(cfg, midi, osc, rolling=True)
        assert midi.send_with_context.call_count == 2

    def test_both_specific_and_toggle_fire_on_stop(self):
        cfg = {
            "midi_send": {
                "transport_stop":   {"cc": 31, "channel": 1, "value": 0},
                "transport_toggle": {"cc": 32, "channel": 1, "value": "rolling"},
            },
            "osc_send": {},
        }
        midi, osc = self._mocks()
        _on_transport_change(cfg, midi, osc, rolling=False)
        assert midi.send_with_context.call_count == 2

    # ── no config – silent no-op ───────────────────────────────────────────────

    def test_no_transport_config_is_silent(self):
        cfg = {"midi_send": {}, "osc_send": {}}
        midi, osc = self._mocks()
        _on_transport_change(cfg, midi, osc, rolling=True)
        midi.send_with_context.assert_not_called()
        osc.send_with_context.assert_not_called()

    def test_missing_midi_send_section_is_silent(self):
        cfg = {"osc_send": {}}
        midi, osc = self._mocks()
        _on_transport_change(cfg, midi, osc, rolling=True)
        midi.send_with_context.assert_not_called()

    # ── rolling value passed through correctly ─────────────────────────────────

    def test_osc_receives_rolling_1_on_start(self):
        cfg = {
            "midi_send": {},
            "osc_send": {"transport_start": {"address": "/t", "args": ["rolling"]}},
        }
        midi, osc = self._mocks()
        _on_transport_change(cfg, midi, osc, rolling=True)
        osc.send_with_context.assert_called_once_with(
            {"address": "/t", "args": ["rolling"]},
            bpm=120.0, raw=0, rolling=1,
        )

    def test_osc_receives_rolling_0_on_stop(self):
        cfg = {
            "midi_send": {},
            "osc_send": {"transport_stop": {"address": "/t", "args": ["rolling"]}},
        }
        midi, osc = self._mocks()
        _on_transport_change(cfg, midi, osc, rolling=False)
        osc.send_with_context.assert_called_once_with(
            {"address": "/t", "args": ["rolling"]},
            bpm=120.0, raw=0, rolling=0,
        )

    # ── mixed midi + osc on same trigger ──────────────────────────────────────

    def test_both_midi_and_osc_fire_on_start(self):
        cfg = {
            "midi_send": {"transport_start": {"cc": 31, "channel": 1, "value": 127}},
            "osc_send":  {"transport_start": {"address": "/H/PLAY", "args": []}},
        }
        midi, osc = self._mocks()
        _on_transport_change(cfg, midi, osc, rolling=True)
        midi.send_with_context.assert_called_once()
        osc.send_with_context.assert_called_once()


# ── _fire_on_quantize dispatch ─────────────────────────────────────────────────

def _fire_on_quantize(cfg: dict, midi_mock, osc_mock,
                      current_bpm: float = 120.0) -> None:
    """Standalone reimplementation of BigTempo._fire_on_quantize."""
    midi_spec = cfg.get("midi_send", {}).get("on_quantize")
    if midi_spec:
        midi_mock.send_with_context(midi_spec, bpm=current_bpm, raw=0)
    osc_spec = cfg.get("osc_send", {}).get("on_quantize")
    if osc_spec:
        osc_mock.send_with_context(osc_spec, bpm=current_bpm, raw=0)


class TestFireOnQuantize:

    def _mocks(self):
        return MagicMock(), MagicMock()

    def test_osc_on_quantize_fires(self):
        cfg = {
            "midi_send": {},
            "osc_send":  {"on_quantize": {"address": "/Hydrogen/BPM", "args": ["bpm"]}},
        }
        midi, osc = self._mocks()
        _fire_on_quantize(cfg, midi, osc, current_bpm=120.0)
        osc.send_with_context.assert_called_once_with(
            {"address": "/Hydrogen/BPM", "args": ["bpm"]},
            bpm=120.0, raw=0,
        )

    def test_midi_on_quantize_fires(self):
        cfg = {
            "midi_send": {"on_quantize": {"cc": 30, "channel": 1, "value": "bpm"}},
            "osc_send":  {},
        }
        midi, osc = self._mocks()
        _fire_on_quantize(cfg, midi, osc, current_bpm=120.0)
        midi.send_with_context.assert_called_once_with(
            {"cc": 30, "channel": 1, "value": "bpm"},
            bpm=120.0, raw=0,
        )

    def test_both_fire_together(self):
        cfg = {
            "midi_send": {"on_quantize": {"cc": 30, "channel": 1, "value": "bpm"}},
            "osc_send":  {"on_quantize": {"address": "/H/BPM", "args": ["bpm"]}},
        }
        midi, osc = self._mocks()
        _fire_on_quantize(cfg, midi, osc, current_bpm=90.0)
        midi.send_with_context.assert_called_once()
        osc.send_with_context.assert_called_once()

    def test_passes_quantized_bpm(self):
        cfg = {
            "midi_send": {},
            "osc_send":  {"on_quantize": {"address": "/H/BPM", "args": ["bpm"]}},
        }
        midi, osc = self._mocks()
        _fire_on_quantize(cfg, midi, osc, current_bpm=137.0)
        _, kwargs = osc.send_with_context.call_args
        assert kwargs["bpm"] == 137.0

    def test_no_config_is_silent(self):
        cfg = {"midi_send": {}, "osc_send": {}}
        midi, osc = self._mocks()
        _fire_on_quantize(cfg, midi, osc)
        midi.send_with_context.assert_not_called()
        osc.send_with_context.assert_not_called()

    def test_on_quantize_independent_of_on_change(self):
        """on_quantize and on_change are separate keys; each fires independently."""
        cfg = {
            "midi_send": {
                "on_change":   {"cc": 31, "channel": 1, "value": "bpm"},
                "on_quantize": {"cc": 30, "channel": 1, "value": "bpm"},
            },
            "osc_send": {},
        }
        midi, osc = self._mocks()
        # on_quantize fires
        _fire_on_quantize(cfg, midi, osc, current_bpm=120.0)
        assert midi.send_with_context.call_args[0][0]["cc"] == 30

    def test_only_fires_when_value_actually_changed(self):
        """
        The app must not call _fire_on_quantize when the quantized value
        equals the raw value (no snapping occurred).  Verified by checking
        that the guard condition abs(snapped - adopted) > 1e-6 works.
        """
        from big_tempo.config import quantize_bpm
        # 120.0 quantized to step 1.0 → still 120.0 → no snap
        raw = 120.0
        snapped = quantize_bpm(raw, {"quantize": 1.0})
        assert abs(snapped - raw) <= 1e-6   # guard would NOT fire

        # 120.3 quantized to step 1.0 → 120.0 → snap occurred
        raw2 = 120.3
        snapped2 = quantize_bpm(raw2, {"quantize": 1.0})
        assert abs(snapped2 - raw2) > 1e-6  # guard WOULD fire
