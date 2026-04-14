"""
tests/test_bpm_math.py – unit tests for pure BPM arithmetic helpers.

No display, JACK or mididings required.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from big_tempo.config import bpm_to_midi_value, clamp_bpm, midi_value_to_bpm

# Shared config used across most tests
CFG = {"min_bpm": 20.0, "max_bpm": 300.0}


class TestClampBpm:
    def test_below_min_snaps_to_min(self):
        assert clamp_bpm(0.0, CFG) == 20.0

    def test_above_max_snaps_to_max(self):
        assert clamp_bpm(500.0, CFG) == 300.0

    def test_at_min_boundary(self):
        assert clamp_bpm(20.0, CFG) == 20.0

    def test_at_max_boundary(self):
        assert clamp_bpm(300.0, CFG) == 300.0

    def test_value_in_range_unchanged(self):
        assert clamp_bpm(120.0, CFG) == 120.0

    def test_uses_cfg_min_max(self):
        narrow = {"min_bpm": 60.0, "max_bpm": 180.0}
        assert clamp_bpm(30.0,  narrow) == 60.0
        assert clamp_bpm(200.0, narrow) == 180.0
        assert clamp_bpm(120.0, narrow) == 120.0

    def test_negative_bpm_clamped(self):
        assert clamp_bpm(-10.0, CFG) == 20.0

    def test_float_precision_preserved(self):
        result = clamp_bpm(120.5, CFG)
        assert abs(result - 120.5) < 1e-9


class TestBpmToMidiValue:
    def test_min_bpm_gives_zero(self):
        assert bpm_to_midi_value(20.0, CFG) == 0

    def test_max_bpm_gives_127(self):
        assert bpm_to_midi_value(300.0, CFG) == 127

    def test_midpoint(self):
        mid_bpm = (20.0 + 300.0) / 2   # 160.0
        value   = bpm_to_midi_value(mid_bpm, CFG)
        # Should be close to 63 or 64 depending on rounding
        assert 62 <= value <= 65

    def test_below_min_clamped_to_zero(self):
        assert bpm_to_midi_value(0.0, CFG) == 0

    def test_above_max_clamped_to_127(self):
        assert bpm_to_midi_value(9999.0, CFG) == 127

    def test_returns_int(self):
        assert isinstance(bpm_to_midi_value(120.0, CFG), int)

    def test_monotonically_increasing(self):
        """Higher BPM must produce a >= MIDI value."""
        bpms   = [20.0, 60.0, 90.0, 120.0, 180.0, 240.0, 300.0]
        values = [bpm_to_midi_value(b, CFG) for b in bpms]
        for a, b in zip(values, values[1:]):
            assert a <= b, f"Not monotone: {values}"


class TestMidiValueToBpm:
    def test_zero_gives_min_bpm(self):
        assert midi_value_to_bpm(0, CFG) == pytest.approx(20.0)

    def test_127_gives_max_bpm(self):
        assert midi_value_to_bpm(127, CFG) == pytest.approx(300.0)

    def test_midpoint(self):
        mid_val = 64
        result  = midi_value_to_bpm(mid_val, CFG)
        # 20 + (64/127)*280 ≈ 161.1
        expected = 20.0 + (64 / 127.0) * 280.0
        assert result == pytest.approx(expected, abs=0.01)

    def test_monotonically_increasing(self):
        """Higher MIDI values must map to higher BPM."""
        for v in range(0, 127):
            assert midi_value_to_bpm(v, CFG) <= midi_value_to_bpm(v + 1, CFG)

    def test_returns_float(self):
        assert isinstance(midi_value_to_bpm(64, CFG), float)

    def test_custom_range(self):
        narrow = {"min_bpm": 60.0, "max_bpm": 180.0}
        assert midi_value_to_bpm(0,   narrow) == pytest.approx(60.0)
        assert midi_value_to_bpm(127, narrow) == pytest.approx(180.0)


class TestRoundTrip:
    """bpm_to_midi_value and midi_value_to_bpm should approximately invert
    each other for values well inside the range."""

    @pytest.mark.parametrize("bpm", [20.0, 60.0, 90.0, 120.0, 160.0, 200.0, 300.0])
    def test_bpm_roundtrip(self, bpm):
        midi_val   = bpm_to_midi_value(bpm, CFG)
        recovered  = midi_value_to_bpm(midi_val, CFG)
        # Quantisation error from 8‑bit MIDI can be up to ~1.1 BPM
        assert abs(recovered - bpm) < 2.5, (
            f"Round‑trip error too large for BPM {bpm}: "
            f"midi={midi_val}, recovered={recovered:.2f}"
        )
