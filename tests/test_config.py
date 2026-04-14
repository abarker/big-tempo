"""
tests/test_config.py – unit tests for config loading and defaults.

These tests do not need JACK, mididings, or a display.
"""

import json
import os
import sys

import pytest

# Ensure the src layout is on the path when running without installation.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from big_tempo.config import DEFAULT_CFG, load_config


class TestDefaultCfg:
    """DEFAULT_CFG must be a complete, self‑consistent baseline."""

    def test_has_required_top_level_keys(self):
        for key in ("midi", "buttons", "min_bpm", "max_bpm", "receive", "send"):
            assert key in DEFAULT_CFG, f"Missing key: {key}"

    def test_min_bpm_less_than_max(self):
        assert DEFAULT_CFG["min_bpm"] < DEFAULT_CFG["max_bpm"]

    def test_buttons_has_required_keys(self):
        for key in ("increment", "repeat_delay_ms", "repeat_ms"):
            assert key in DEFAULT_CFG["buttons"], f"Missing buttons key: {key}"

    def test_midi_has_required_keys(self):
        for key in ("client_name", "channel"):
            assert key in DEFAULT_CFG["midi"], f"Missing midi key: {key}"

    def test_receive_and_send_are_dicts(self):
        assert isinstance(DEFAULT_CFG["receive"], dict)
        assert isinstance(DEFAULT_CFG["send"],    dict)


class TestLoadConfig:
    """load_config() must merge user JSON correctly over the defaults."""

    def test_returns_defaults_when_file_missing(self, tmp_path):
        cfg = load_config(str(tmp_path / "nonexistent.json"))
        assert cfg["min_bpm"] == DEFAULT_CFG["min_bpm"]
        assert cfg["max_bpm"] == DEFAULT_CFG["max_bpm"]

    def test_overrides_scalar_value(self, tmp_path):
        user = {"min_bpm": 40.0}
        f = tmp_path / "cfg.json"
        f.write_text(json.dumps(user))
        cfg = load_config(str(f))
        assert cfg["min_bpm"] == 40.0
        assert cfg["max_bpm"] == DEFAULT_CFG["max_bpm"]  # untouched

    def test_merges_nested_dict(self, tmp_path):
        """Sub‑keys of a nested section should merge, not replace."""
        user = {"buttons": {"increment": 2.0}}
        f = tmp_path / "cfg.json"
        f.write_text(json.dumps(user))
        cfg = load_config(str(f))
        # Override took effect
        assert cfg["buttons"]["increment"] == 2.0
        # The other sub‑keys survive the merge
        assert "repeat_delay_ms" in cfg["buttons"]
        assert "repeat_ms"       in cfg["buttons"]

    def test_replaces_scalar_with_new_dict(self, tmp_path):
        """A key that is a scalar in defaults can be replaced with a dict."""
        user = {"min_bpm": {"value": 30.0}}   # contrived, but valid JSON
        f = tmp_path / "cfg.json"
        f.write_text(json.dumps(user))
        cfg = load_config(str(f))
        assert cfg["min_bpm"] == {"value": 30.0}

    def test_receive_mapping_survives(self, tmp_path):
        user = {
            "receive": {
                "CC20": {"action": "up",   "amount": 1.0},
                "CC21": {"action": "down", "amount": 2.0},
            }
        }
        f = tmp_path / "cfg.json"
        f.write_text(json.dumps(user))
        cfg = load_config(str(f))
        assert cfg["receive"]["CC20"]["action"] == "up"
        assert cfg["receive"]["CC21"]["amount"] == 2.0

    def test_send_mapping_survives(self, tmp_path):
        user = {"send": {"on_change": {"cc": 42, "channel": 2}}}
        f = tmp_path / "cfg.json"
        f.write_text(json.dumps(user))
        cfg = load_config(str(f))
        assert cfg["send"]["on_change"]["cc"]      == 42
        assert cfg["send"]["on_change"]["channel"] == 2

    def test_invalid_json_returns_defaults(self, tmp_path, capsys):
        f = tmp_path / "bad.json"
        f.write_text("{ this is not valid json }")
        cfg = load_config(str(f))
        # Should not raise, should return defaults
        assert cfg["min_bpm"] == DEFAULT_CFG["min_bpm"]
        # A warning should have been printed to stderr
        captured = capsys.readouterr()
        assert "Warning" in captured.err

    def test_does_not_mutate_default_cfg(self, tmp_path):
        """load_config() must deep‑copy DEFAULT_CFG, not modify it in place."""
        user = {"min_bpm": 999.0, "buttons": {"increment": 99.0}}
        f = tmp_path / "cfg.json"
        f.write_text(json.dumps(user))
        load_config(str(f))
        # DEFAULT_CFG must be unchanged
        assert DEFAULT_CFG["min_bpm"]          == 20.0
        assert DEFAULT_CFG["buttons"]["increment"] == 1.0
