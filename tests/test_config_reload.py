"""
tests/test_config_reload.py – tests for the config hot-reload mechanism.

Rather than importing big_tempo.app (which pulls in tkinter), the reload
logic is reimplemented as standalone functions mirroring the real methods.
This is the same pattern used by test_transport.py.
No display, JACK, or mididings required.
"""

import datetime
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from big_tempo.config import DEFAULT_CFG, load_config
from big_tempo.config import DEFAULT_CONFIG_PATH


# ── Standalone reimplementations of the reload methods ────────────────────────

def _get_cfg_mtime(cfg_path: str) -> float:
    """Mirrors BigTempo._get_cfg_mtime."""
    try:
        return os.stat(cfg_path).st_mtime
    except OSError:
        return 0.0


def _check_config_reload(app) -> None:
    """Mirrors BigTempo._check_config_reload."""
    mtime = _get_cfg_mtime(app._cfg_path)
    if mtime == 0.0 or mtime == app._cfg_mtime:
        return
    app._cfg_mtime = mtime

    new_cfg = load_config(app._cfg_path)
    if new_cfg is None:
        return

    # Capture before/after comparison values before the swap
    old_midi_name = app.cfg.get("midi", {}).get("client_name")
    new_midi_name = new_cfg.get("midi", {}).get("client_name")

    app.cfg      = new_cfg
    app.midi.cfg = new_cfg
    # Fresh OscSender pool on every reload (lazy, so this is free)
    from big_tempo.osc import OscSender as _OscSender
    app.osc = _OscSender(new_cfg)

    restart_notes = []
    if old_midi_name != new_midi_name:
        restart_notes.append(
            f"  midi.client_name: '{old_midi_name}' → '{new_midi_name}'"
            " (restart required)"
        )

    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] config reloaded: {app._cfg_path}", file=sys.stderr, flush=True)
    for note in restart_notes:
        print(note, file=sys.stderr, flush=True)


# ── Minimal fake app ──────────────────────────────────────────────────────────

def _make_app(cfg_path: str, cfg: dict):
    class FakeApp:
        pass
    app          = FakeApp()
    app.cfg      = dict(cfg)
    app.midi     = MagicMock()
    app.midi.cfg = app.cfg
    app.osc      = MagicMock()
    app.osc.cfg  = app.cfg
    app._cfg_path  = cfg_path
    app._cfg_mtime = 0.0
    return app


# ── _get_cfg_mtime ─────────────────────────────────────────────────────────────

class TestGetCfgMtime:
    def test_returns_mtime_for_existing_file(self, tmp_path):
        f = tmp_path / "config.py"
        f.write_text('{"debug": False}')
        assert _get_cfg_mtime(str(f)) > 0.0

    def test_returns_zero_when_file_absent(self, tmp_path):
        assert _get_cfg_mtime(str(tmp_path / "nonexistent.py")) == 0.0

    def test_mtime_increases_after_write(self, tmp_path):
        f = tmp_path / "config.py"
        f.write_text('{"debug": False}')
        t1 = _get_cfg_mtime(str(f))
        time.sleep(0.02)
        f.write_text('{"debug": True}')
        t2 = _get_cfg_mtime(str(f))
        assert t2 >= t1


# ── _check_config_reload ───────────────────────────────────────────────────────

class TestCheckConfigReload:

    def test_no_reload_when_mtime_unchanged(self, tmp_path):
        f = tmp_path / "cfg.py"
        f.write_text('{"min_bpm": 30.0}')
        app = _make_app(str(f), dict(DEFAULT_CFG))
        app._cfg_mtime = _get_cfg_mtime(str(f))
        original_cfg = app.cfg
        _check_config_reload(app)
        assert app.cfg is original_cfg

    def test_reload_triggered_on_mtime_change(self, tmp_path):
        f = tmp_path / "cfg.py"
        f.write_text('{"min_bpm": 20.0}')
        app = _make_app(str(f), dict(DEFAULT_CFG))
        _check_config_reload(app)
        assert app.cfg is not DEFAULT_CFG

    def test_new_values_applied(self, tmp_path):
        f = tmp_path / "cfg.py"
        f.write_text('{"min_bpm": 55.0, "max_bpm": 250.0}')
        app = _make_app(str(f), dict(DEFAULT_CFG))
        _check_config_reload(app)
        assert app.cfg["min_bpm"] == 55.0
        assert app.cfg["max_bpm"] == 250.0

    def test_midi_cfg_reference_updated(self, tmp_path):
        f = tmp_path / "cfg.py"
        f.write_text('{"min_bpm": 40.0}')
        app = _make_app(str(f), dict(DEFAULT_CFG))
        _check_config_reload(app)
        assert app.midi.cfg is app.cfg

    def test_osc_recreated_on_every_reload(self, tmp_path):
        """OscSender is always replaced on reload (fresh lazy pool)."""
        f = tmp_path / "cfg.py"
        f.write_text('{"min_bpm": 40.0}')
        app = _make_app(str(f), dict(DEFAULT_CFG))
        old_osc = app.osc
        _check_config_reload(app)
        assert app.osc is not old_osc

    def test_osc_cfg_points_to_new_cfg(self, tmp_path):
        """The new OscSender must reference the reloaded config dict."""
        f = tmp_path / "cfg.py"
        f.write_text('{"min_bpm": 40.0}')
        app = _make_app(str(f), dict(DEFAULT_CFG))
        _check_config_reload(app)
        assert app.osc.cfg is app.cfg

    def test_no_reload_when_file_absent(self, tmp_path):
        app = _make_app(str(tmp_path / "nonexistent.py"), dict(DEFAULT_CFG))
        original_cfg = app.cfg
        _check_config_reload(app)
        assert app.cfg is original_cfg

    def test_prints_timestamp_to_stderr(self, tmp_path, capsys):
        f = tmp_path / "cfg.py"
        f.write_text('{"min_bpm": 30.0}')
        app = _make_app(str(f), dict(DEFAULT_CFG))
        _check_config_reload(app)
        assert "config reloaded" in capsys.readouterr().err

    def test_second_check_unchanged_does_not_reload(self, tmp_path):
        f = tmp_path / "cfg.py"
        f.write_text('{"min_bpm": 30.0}')
        app = _make_app(str(f), dict(DEFAULT_CFG))
        _check_config_reload(app)
        cfg_after_first = app.cfg
        _check_config_reload(app)
        assert app.cfg is cfg_after_first

    def test_quantize_change_applied_live(self, tmp_path):
        f = tmp_path / "cfg.py"
        f.write_text('{"quantize": 0.5, "quantize_jack": True}')
        app = _make_app(str(f), dict(DEFAULT_CFG))
        _check_config_reload(app)
        assert app.cfg["quantize"]      == 0.5
        assert app.cfg["quantize_jack"] is True

    def test_receive_mapping_change_applied_live(self, tmp_path):
        f = tmp_path / "cfg.py"
        f.write_text(
            '{"receive": {"CC20": {"action": "up", "amount": 2.0}}}'
        )
        app = _make_app(str(f), dict(DEFAULT_CFG))
        _check_config_reload(app)
        assert app.cfg["receive"]["CC20"]["amount"] == 2.0

    def test_send_mapping_change_applied_live(self, tmp_path):
        f = tmp_path / "cfg.py"
        f.write_text(
            '{"send": {"on_change": [{"send": "MIDI", "cc": 42, "channel": 1, "value": "bpm"}]}}'
        )
        app = _make_app(str(f), dict(DEFAULT_CFG))
        _check_config_reload(app)
        assert app.cfg["send"]["on_change"][0]["cc"] == 42

    def test_midi_client_name_change_warns(self, tmp_path, capsys):
        f = tmp_path / "cfg.py"
        f.write_text('{"midi": {"client_name": "new_name"}}')
        cfg = {**DEFAULT_CFG, "midi": {"client_name": "old_name", "channel": 1}}
        app = _make_app(str(f), cfg)
        _check_config_reload(app)
        assert "restart required" in capsys.readouterr().err
