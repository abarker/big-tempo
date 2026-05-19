"""
tests/test_config.py – unit tests for config loading and defaults.

These tests do not need JACK, mididings, or a display.
Config files are written as Python dict literals (parsed by ast.literal_eval).
"""

import os
import sys

import pytest

# Ensure the src layout is on the path when running without installation.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from big_tempo.config import DEFAULT_CFG, load_config


# ── Helpers ────────────────────────────────────────────────────────────────────

def write_cfg(path, content: str):
    """Write *content* (a Python dict literal string) to *path*."""
    path.write_text(content, encoding="utf-8")


# ── Default config ─────────────────────────────────────────────────────────────

class TestDefaultCfg:
    """DEFAULT_CFG must be a complete, self-consistent baseline."""

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


# ── Config loader ──────────────────────────────────────────────────────────────

class TestLoadConfig:
    """load_config() must merge user Python-dict configs correctly over defaults."""

    def test_returns_defaults_when_file_missing(self, tmp_path):
        cfg = load_config(str(tmp_path / "nonexistent.py"))
        assert cfg["min_bpm"] == DEFAULT_CFG["min_bpm"]
        assert cfg["max_bpm"] == DEFAULT_CFG["max_bpm"]

    def test_overrides_scalar_value(self, tmp_path):
        f = tmp_path / "cfg.py"
        write_cfg(f, '{"min_bpm": 40.0}')
        cfg = load_config(str(f))
        assert cfg["min_bpm"] == 40.0
        assert cfg["max_bpm"] == DEFAULT_CFG["max_bpm"]  # untouched

    def test_merges_nested_dict(self, tmp_path):
        """Sub-keys of a nested section should merge, not replace."""
        f = tmp_path / "cfg.py"
        write_cfg(f, '{"buttons": {"increment": 2.0}}')
        cfg = load_config(str(f))
        assert cfg["buttons"]["increment"] == 2.0
        assert "repeat_delay_ms" in cfg["buttons"]
        assert "repeat_ms"       in cfg["buttons"]

    def test_replaces_scalar_with_new_dict(self, tmp_path):
        """A key that is a scalar in defaults can be replaced with a dict."""
        f = tmp_path / "cfg.py"
        write_cfg(f, '{"min_bpm": {"value": 30.0}}')
        cfg = load_config(str(f))
        assert cfg["min_bpm"] == {"value": 30.0}

    def test_receive_mapping_survives(self, tmp_path):
        f = tmp_path / "cfg.py"
        write_cfg(f, """
{
    "receive": {
        "CC20": {"action": "up",   "amount": 1.0},
        "CC21": {"action": "down", "amount": 2.0},
    }
}
""")
        cfg = load_config(str(f))
        assert cfg["receive"]["CC20"]["action"] == "up"
        assert cfg["receive"]["CC21"]["amount"] == 2.0

    def test_send_mapping_survives(self, tmp_path):
        f = tmp_path / "cfg.py"
        write_cfg(f, '{"send": {"on_change": [{"send": "MIDI", "cc": 42, "channel": 2, "value": "bpm"}]}}')
        cfg = load_config(str(f))
        assert cfg["send"]["on_change"][0]["cc"]      == 42
        assert cfg["send"]["on_change"][0]["channel"] == 2

    def test_inline_comments_are_ignored(self, tmp_path):
        """# comments must be stripped cleanly by the Python tokeniser."""
        f = tmp_path / "cfg.py"
        write_cfg(f, """
{
    # raise the tempo floor for this gig
    "min_bpm": 60.0,          # was 20.0
    "max_bpm": 240.0,         # tighter range
}
""")
        cfg = load_config(str(f))
        assert cfg["min_bpm"] == 60.0
        assert cfg["max_bpm"] == 240.0

    def test_trailing_commas_are_accepted(self, tmp_path):
        """Python dict literals allow trailing commas; JSON does not."""
        f = tmp_path / "cfg.py"
        write_cfg(f, '{"min_bpm": 30.0,}')
        cfg = load_config(str(f))
        assert cfg["min_bpm"] == 30.0

    def test_invalid_syntax_returns_defaults(self, tmp_path, capsys):
        f = tmp_path / "bad.py"
        write_cfg(f, "{ this is not valid }")
        cfg = load_config(str(f))
        assert cfg["min_bpm"] == DEFAULT_CFG["min_bpm"]
        captured = capsys.readouterr()
        assert "Warning" in captured.err

    def test_non_dict_literal_returns_defaults(self, tmp_path, capsys):
        """A file containing a list instead of a dict should warn and fall back."""
        f = tmp_path / "bad.py"
        write_cfg(f, "[1, 2, 3]")
        cfg = load_config(str(f))
        assert cfg["min_bpm"] == DEFAULT_CFG["min_bpm"]
        captured = capsys.readouterr()
        assert "Warning" in captured.err

    def test_does_not_mutate_default_cfg(self, tmp_path):
        """load_config() must deep-copy DEFAULT_CFG, not modify it in place."""
        f = tmp_path / "cfg.py"
        write_cfg(f, '{"min_bpm": 999.0, "buttons": {"increment": 99.0}}')
        load_config(str(f))
        assert DEFAULT_CFG["min_bpm"]              == 20.0
        assert DEFAULT_CFG["buttons"]["increment"] == 1.0
