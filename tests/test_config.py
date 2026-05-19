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

from big_tempo.config import DEFAULT_CFG, load_config, validate_config


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


# ── Validation ─────────────────────────────────────────────────────────────────

def _valid_midi():
    return {"send": "MIDI", "cc": 30, "channel": 1, "value": "bpm"}

def _valid_osc():
    return {"send": "OSC", "host": "127.0.0.1", "port": 9000, "address": "/x"}

def _valid_cfg(**overrides):
    """Minimal fully-valid config with no warnings."""
    cfg = {
        "min_bpm": 20.0, "max_bpm": 300.0,
        "quantize": None, "buttons": {"increment": 1.0},
        "receive": {}, "send": {},
    }
    cfg.update(overrides)
    return cfg


class TestValidateConfig:

    # ── Clean config ───────────────────────────────────────────────────────────

    def test_valid_config_produces_no_warnings(self):
        assert validate_config(_valid_cfg()) == []

    def test_empty_config_produces_no_warnings(self):
        assert validate_config({}) == []

    def test_full_valid_send_produces_no_warnings(self):
        cfg = _valid_cfg(send={
            "on_change": [_valid_midi(), _valid_osc()],
            "transport_start": [_valid_midi()],
        })
        assert validate_config(cfg) == []

    # ── Legacy keys ───────────────────────────────────────────────────────────

    def test_legacy_midi_send_key_warns(self):
        ws = validate_config({"midi_send": {}})
        assert any("midi_send" in w for w in ws)

    def test_legacy_osc_send_key_warns(self):
        ws = validate_config({"osc_send": {}})
        assert any("osc_send" in w for w in ws)

    def test_legacy_osc_key_warns(self):
        ws = validate_config({"osc": {"host": "127.0.0.1", "port": 9000}})
        assert any("'osc'" in w for w in ws)

    def test_legacy_key_message_mentions_send(self):
        ws = validate_config({"midi_send": {}})
        assert any("send" in w.lower() for w in ws)

    # ── Scalar validation ─────────────────────────────────────────────────────

    def test_min_bpm_gte_max_bpm_warns(self):
        ws = validate_config(_valid_cfg(min_bpm=300.0, max_bpm=20.0))
        assert any("min_bpm" in w and "max_bpm" in w for w in ws)

    def test_min_bpm_equal_max_bpm_warns(self):
        ws = validate_config(_valid_cfg(min_bpm=120.0, max_bpm=120.0))
        assert len(ws) > 0

    def test_valid_bpm_range_no_warning(self):
        ws = validate_config(_valid_cfg(min_bpm=20.0, max_bpm=300.0))
        assert not any("min_bpm" in w for w in ws)

    def test_negative_quantize_warns(self):
        ws = validate_config(_valid_cfg(quantize=-1.0))
        assert any("quantize" in w for w in ws)

    def test_zero_quantize_warns(self):
        ws = validate_config(_valid_cfg(quantize=0))
        assert any("quantize" in w for w in ws)

    def test_valid_quantize_no_warning(self):
        assert not any("quantize" in w for w in validate_config(_valid_cfg(quantize=1.0)))

    def test_none_quantize_no_warning(self):
        assert not any("quantize" in w for w in validate_config(_valid_cfg(quantize=None)))

    def test_negative_buttons_increment_warns(self):
        ws = validate_config(_valid_cfg(buttons={"increment": -1.0}))
        assert any("increment" in w for w in ws)

    def test_zero_buttons_increment_warns(self):
        ws = validate_config(_valid_cfg(buttons={"increment": 0}))
        assert any("increment" in w for w in ws)

    # ── receive validation ────────────────────────────────────────────────────

    def test_unknown_action_warns(self):
        cfg = _valid_cfg(receive={"CC20": {"action": "down2", "amount": 5.0}})
        ws = validate_config(cfg)
        assert any("down2" in w for w in ws)

    def test_unknown_action_lists_valid_actions(self):
        cfg = _valid_cfg(receive={"CC20": {"action": "dance"}})
        ws = validate_config(cfg)
        assert any("up" in w for w in ws)   # "up" should appear in the valid-actions list

    def test_missing_action_warns(self):
        cfg = _valid_cfg(receive={"CC20": {"amount": 1.0}})
        ws = validate_config(cfg)
        assert any("action" in w for w in ws)

    def test_valid_action_no_warning(self):
        for action in ("up", "down", "set", "list_append", "list_next",
                       "list_clear", "osc_only", "midi_only"):
            cfg = _valid_cfg(receive={"CC20": {"action": action}})
            assert validate_config(cfg) == [], f"unexpected warning for action {action!r}"

    def test_bad_cc_key_format_warns(self):
        cfg = _valid_cfg(receive={"CTRL20": {"action": "up"}})
        ws = validate_config(cfg)
        assert any("CC<number>" in w for w in ws)

    def test_cc_out_of_range_warns(self):
        cfg = _valid_cfg(receive={"CC200": {"action": "up"}})
        ws = validate_config(cfg)
        assert any("200" in w for w in ws)

    def test_receive_entry_not_dict_warns(self):
        cfg = _valid_cfg(receive={"CC20": "up"})
        ws = validate_config(cfg)
        assert len(ws) > 0

    def test_receive_send_not_list_warns(self):
        cfg = _valid_cfg(receive={"CC20": {"action": "up", "send": _valid_osc()}})
        ws = validate_config(cfg)
        assert any("list" in w for w in ws)

    def test_receive_send_list_validated(self):
        bad_spec = {"send": "MIDI", "cc": 30, "channel": 1}   # missing value
        cfg = _valid_cfg(receive={"CC20": {"action": "up", "send": [bad_spec]}})
        ws = validate_config(cfg)
        assert any("value" in w for w in ws)

    def test_valid_receive_with_send_no_warning(self):
        cfg = _valid_cfg(receive={
            "CC20": {"action": "up", "amount": 1.0, "send": [_valid_osc()]},
        })
        assert validate_config(cfg) == []

    # ── send section ──────────────────────────────────────────────────────────

    def test_unknown_trigger_warns(self):
        cfg = _valid_cfg(send={"on_foobar": [_valid_midi()]})
        ws = validate_config(cfg)
        assert any("on_foobar" in w for w in ws)

    def test_unknown_trigger_lists_valid_triggers(self):
        cfg = _valid_cfg(send={"bogus": [_valid_midi()]})
        ws = validate_config(cfg)
        assert any("on_change" in w for w in ws)

    def test_all_valid_triggers_no_warning(self):
        for trigger in ("on_change", "on_quantize", "transport_start",
                        "transport_stop", "transport_toggle"):
            cfg = _valid_cfg(send={trigger: [_valid_midi()]})
            assert validate_config(cfg) == [], f"unexpected warning for trigger {trigger!r}"

    def test_send_value_not_list_warns(self):
        """Old single-dict format should produce a clear error."""
        cfg = _valid_cfg(send={"on_change": _valid_midi()})  # dict, not list
        ws = validate_config(cfg)
        assert any("list" in w for w in ws)

    def test_send_action_missing_send_key_warns(self):
        cfg = _valid_cfg(send={"on_change": [{"cc": 30, "channel": 1, "value": "bpm"}]})
        ws = validate_config(cfg)
        assert any("'send'" in w or '"send"' in w for w in ws)

    def test_send_action_unknown_type_warns(self):
        cfg = _valid_cfg(send={"on_change": [{"send": "HTTP", "url": "/x"}]})
        ws = validate_config(cfg)
        assert any("HTTP" in w for w in ws)

    # ── MIDI action validation ─────────────────────────────────────────────────

    def test_midi_missing_cc_warns(self):
        spec = {"send": "MIDI", "channel": 1, "value": "bpm"}
        ws = validate_config(_valid_cfg(send={"on_change": [spec]}))
        assert any("'cc'" in w for w in ws)

    def test_midi_missing_channel_warns(self):
        spec = {"send": "MIDI", "cc": 30, "value": "bpm"}
        ws = validate_config(_valid_cfg(send={"on_change": [spec]}))
        assert any("'channel'" in w for w in ws)

    def test_midi_missing_value_warns(self):
        spec = {"send": "MIDI", "cc": 30, "channel": 1}
        ws = validate_config(_valid_cfg(send={"on_change": [spec]}))
        assert any("'value'" in w for w in ws)

    def test_midi_unknown_value_token_warns(self):
        spec = {"send": "MIDI", "cc": 30, "channel": 1, "value": "speed"}
        ws = validate_config(_valid_cfg(send={"on_change": [spec]}))
        assert any("speed" in w for w in ws)

    def test_midi_value_out_of_range_warns(self):
        spec = {"send": "MIDI", "cc": 30, "channel": 1, "value": 200}
        ws = validate_config(_valid_cfg(send={"on_change": [spec]}))
        assert any("200" in w for w in ws)

    def test_midi_cc_out_of_range_warns(self):
        spec = {"send": "MIDI", "cc": 200, "channel": 1, "value": "bpm"}
        ws = validate_config(_valid_cfg(send={"on_change": [spec]}))
        assert any("200" in w for w in ws)

    def test_midi_channel_out_of_range_warns(self):
        spec = {"send": "MIDI", "cc": 30, "channel": 17, "value": "bpm"}
        ws = validate_config(_valid_cfg(send={"on_change": [spec]}))
        assert any("17" in w for w in ws)

    def test_midi_valid_value_tokens_no_warning(self):
        for token in ("bpm", "raw", "rolling"):
            spec = {"send": "MIDI", "cc": 30, "channel": 1, "value": token}
            assert validate_config(_valid_cfg(send={"on_change": [spec]})) == []

    def test_midi_valid_literal_value_no_warning(self):
        spec = {"send": "MIDI", "cc": 30, "channel": 1, "value": 64}
        assert validate_config(_valid_cfg(send={"on_change": [spec]})) == []

    # ── OSC action validation ──────────────────────────────────────────────────

    def test_osc_missing_host_warns(self):
        spec = {"send": "OSC", "port": 9000, "address": "/x"}
        ws = validate_config(_valid_cfg(send={"on_change": [spec]}))
        assert any("'host'" in w for w in ws)

    def test_osc_missing_port_warns(self):
        spec = {"send": "OSC", "host": "127.0.0.1", "address": "/x"}
        ws = validate_config(_valid_cfg(send={"on_change": [spec]}))
        assert any("'port'" in w for w in ws)

    def test_osc_missing_address_warns(self):
        spec = {"send": "OSC", "host": "127.0.0.1", "port": 9000}
        ws = validate_config(_valid_cfg(send={"on_change": [spec]}))
        assert any("'address'" in w for w in ws)

    def test_osc_address_without_slash_warns(self):
        spec = {"send": "OSC", "host": "127.0.0.1", "port": 9000, "address": "HydrogenBPM"}
        ws = validate_config(_valid_cfg(send={"on_change": [spec]}))
        assert any("/" in w for w in ws)

    def test_osc_port_out_of_range_warns(self):
        spec = {"send": "OSC", "host": "127.0.0.1", "port": 99999, "address": "/x"}
        ws = validate_config(_valid_cfg(send={"on_change": [spec]}))
        assert any("99999" in w for w in ws)

    def test_osc_args_not_list_warns(self):
        spec = {"send": "OSC", "host": "127.0.0.1", "port": 9000,
                "address": "/x", "args": "bpm"}
        ws = validate_config(_valid_cfg(send={"on_change": [spec]}))
        assert any("args" in w for w in ws)

    def test_osc_valid_spec_no_warning(self):
        assert validate_config(_valid_cfg(send={"on_change": [_valid_osc()]})) == []

    def test_osc_with_args_no_warning(self):
        spec = {**_valid_osc(), "args": ["bpm"]}
        assert validate_config(_valid_cfg(send={"on_change": [spec]})) == []

    # ── load_config integration ───────────────────────────────────────────────

    def test_warnings_printed_to_stderr_on_load(self, tmp_path, capsys):
        f = tmp_path / "cfg.py"
        f.write_text('{"receive": {"CC20": {"action": "dance"}}}')
        load_config(str(f))
        assert "dance" in capsys.readouterr().err

    def test_multiple_warnings_all_printed(self, tmp_path, capsys):
        f = tmp_path / "cfg.py"
        f.write_text('{"receive": {"CC20": {"action": "bad1"}, "CC21": {"action": "bad2"}}}')
        load_config(str(f))
        err = capsys.readouterr().err
        assert "bad1" in err
        assert "bad2" in err

    def test_config_returned_despite_warnings(self, tmp_path):
        f = tmp_path / "cfg.py"
        f.write_text('{"min_bpm": 99.0, "receive": {"CC20": {"action": "dance"}}}')
        cfg = load_config(str(f))
        assert cfg["min_bpm"] == 99.0   # valid value was still applied

    def test_clean_config_no_stderr(self, tmp_path, capsys):
        f = tmp_path / "cfg.py"
        f.write_text('{"min_bpm": 40.0}')
        load_config(str(f))
        assert capsys.readouterr().err == ""
