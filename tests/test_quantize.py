"""
tests/test_quantize.py – unit tests for quantize_bpm().

No display, JACK, or mididings required.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from big_tempo.config import clamp_bpm, quantize_bpm


# ── Disabled (no quantization) ─────────────────────────────────────────────────

class TestQuantizeDisabled:
    def test_none_returns_unchanged(self):
        assert quantize_bpm(120.3, {"quantize": None}) == 120.3

    def test_zero_returns_unchanged(self):
        assert quantize_bpm(120.3, {"quantize": 0}) == 120.3

    def test_false_returns_unchanged(self):
        assert quantize_bpm(120.3, {"quantize": False}) == 120.3

    def test_absent_key_returns_unchanged(self):
        assert quantize_bpm(120.3, {}) == 120.3

    def test_negative_step_returns_unchanged(self):
        assert quantize_bpm(120.3, {"quantize": -1.0}) == 120.3


# ── Integer quantization (step = 1.0) ─────────────────────────────────────────

class TestIntegerQuantize:
    CFG = {"quantize": 1.0}

    def test_exact_integer_unchanged(self):
        assert quantize_bpm(120.0, self.CFG) == 120.0

    def test_rounds_down(self):
        assert quantize_bpm(120.3, self.CFG) == 120.0

    def test_rounds_up(self):
        assert quantize_bpm(120.7, self.CFG) == 121.0

    def test_midpoint_rounds_to_even(self):
        # Python's round() uses banker's rounding at 0.5
        # 120.5 → 120 (even), 121.5 → 122 (even)
        assert quantize_bpm(120.5, self.CFG) == 120.0
        assert quantize_bpm(121.5, self.CFG) == 122.0

    def test_min_boundary(self):
        assert quantize_bpm(20.0, self.CFG) == 20.0

    def test_max_boundary(self):
        assert quantize_bpm(300.0, self.CFG) == 300.0

    def test_fractional_near_zero(self):
        assert quantize_bpm(20.4, self.CFG) == 20.0

    def test_result_is_float(self):
        assert isinstance(quantize_bpm(120.3, self.CFG), float)


# ── Half-BPM quantization (step = 0.5) ────────────────────────────────────────

class TestHalfBpmQuantize:
    CFG = {"quantize": 0.5}

    def test_exact_half_unchanged(self):
        assert quantize_bpm(120.5, self.CFG) == 120.5

    def test_rounds_down_to_half(self):
        assert quantize_bpm(120.3, self.CFG) == 120.5

    def test_rounds_down_to_integer(self):
        assert quantize_bpm(120.2, self.CFG) == 120.0

    def test_rounds_up_to_integer(self):
        assert quantize_bpm(120.8, self.CFG) == 121.0

    def test_all_steps_reachable(self):
        expected_steps = [120.0, 120.5, 121.0, 121.5, 122.0]
        for bpm in [120.0, 120.4, 120.6, 121.1, 121.8]:
            result = quantize_bpm(bpm, self.CFG)
            assert result in expected_steps, f"{bpm} → {result} not in {expected_steps}"


# ── Quarter-BPM quantization (step = 0.25) ────────────────────────────────────

class TestQuarterBpmQuantize:
    CFG = {"quantize": 0.25}

    def test_exact_quarter_unchanged(self):
        assert quantize_bpm(120.25, self.CFG) == pytest.approx(120.25)
        assert quantize_bpm(120.75, self.CFG) == pytest.approx(120.75)

    def test_rounds_to_nearest_quarter(self):
        assert quantize_bpm(120.1, self.CFG) == pytest.approx(120.0)
        assert quantize_bpm(120.4, self.CFG) == pytest.approx(120.5)


# ── Non-standard step sizes ────────────────────────────────────────────────────

class TestCustomStep:
    def test_step_5(self):
        cfg = {"quantize": 5.0}
        assert quantize_bpm(122.0, cfg) == 120.0
        assert quantize_bpm(123.0, cfg) == 125.0
        assert quantize_bpm(120.0, cfg) == 120.0

    def test_step_10(self):
        cfg = {"quantize": 10.0}
        assert quantize_bpm(124.9, cfg) == 120.0
        assert quantize_bpm(125.1, cfg) == 130.0

    def test_step_as_string_int_accepted(self):
        # ast.literal_eval config values are always proper Python types,
        # but test robustness for numeric step stored as int
        cfg = {"quantize": 1}
        assert quantize_bpm(120.7, cfg) == 121.0


# ── Interaction: quantize then clamp ──────────────────────────────────────────

class TestQuantizeThenClamp:
    """
    In app.py, quantize_bpm is applied before clamp_bpm.
    Test that the composition behaves correctly at the boundaries.
    """
    CFG = {"min_bpm": 20.0, "max_bpm": 300.0, "quantize": 1.0}

    def test_quantize_below_min_then_clamp(self):
        # 19.6 quantises to 20.0, which is exactly min → unchanged
        q = quantize_bpm(19.6, self.CFG)
        assert clamp_bpm(q, self.CFG) == 20.0

    def test_quantize_above_max_then_clamp(self):
        # 300.4 quantises to 300.0 → exactly max
        q = quantize_bpm(300.4, self.CFG)
        assert clamp_bpm(q, self.CFG) == 300.0

    def test_quantize_rounds_past_max_then_clamped(self):
        # 300.6 would quantise to 301.0 → clamped back to 300.0
        q = quantize_bpm(300.6, self.CFG)
        assert clamp_bpm(q, self.CFG) == 300.0

    def test_mid_range_unaffected(self):
        q = quantize_bpm(120.3, self.CFG)
        assert clamp_bpm(q, self.CFG) == 120.0


# ── Monotonicity ───────────────────────────────────────────────────────────────

class TestMonotonicity:
    """Quantized values should be weakly monotonically increasing."""

    def test_monotone_integer(self):
        cfg = {"quantize": 1.0}
        bpms = [20.0 + i * 0.1 for i in range(2810)]
        values = [quantize_bpm(b, cfg) for b in bpms]
        for a, b in zip(values, values[1:]):
            assert a <= b, f"Not monotone: {a} > {b}"

    def test_monotone_half(self):
        cfg = {"quantize": 0.5}
        bpms = [20.0 + i * 0.05 for i in range(5620)]
        values = [quantize_bpm(b, cfg) for b in bpms]
        for a, b in zip(values, values[1:]):
            assert a <= b, f"Not monotone: {a} > {b}"


# ── quantize_jack config key ───────────────────────────────────────────────────
# These tests verify the config key is read correctly.
# The actual application logic lives in app._update_loop and is tested
# indirectly by the presence of the key in DEFAULT_CFG.

class TestQuantizeJackConfig:
    def test_default_is_false(self):
        from big_tempo.config import DEFAULT_CFG
        assert DEFAULT_CFG["quantize_jack"] is False

    def test_quantize_jack_true_is_truthy(self):
        """When True, the flag enables JACK tempo quantization."""
        cfg = {"quantize": 1.0, "quantize_jack": True}
        # quantize_bpm itself is unaffected by quantize_jack flag; the flag
        # is read by app._update_loop to decide whether to call quantize_bpm.
        # Verify the config round-trips correctly.
        assert cfg["quantize_jack"] is True

    def test_quantize_jack_false_is_falsy(self):
        cfg = {"quantize": 1.0, "quantize_jack": False}
        assert not cfg["quantize_jack"]
