"""
config.py – configuration defaults, loader, and pure BPM arithmetic helpers.

All functions in this module are free of tkinter / JACK / mididings so they
can be imported and tested on any machine.
"""

import copy
import json
import os
import sys
from typing import Optional

# ── Built‑in defaults ──────────────────────────────────────────────────────────
DEFAULT_CFG: dict = {
    "midi": {
        "client_name": "big_tempo_midi",
        "channel": 1,
    },
    "buttons": {
        "increment": 1.0,
        "repeat_delay_ms": 400,
        "repeat_ms": 80,
    },
    "min_bpm": 20.0,
    "max_bpm": 300.0,
    "receive": {},
    "send": {},
}

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/big-tempo/config.json")


# ── Loader ─────────────────────────────────────────────────────────────────────
def load_config(path: Optional[str] = None) -> dict:
    """
    Return a config dict merged from built‑in defaults and the JSON file at
    *path* (default: ``~/.config/big-tempo/config.json``).

    Merge strategy: deep‑copy the defaults, then for every top‑level key
    present in the user file:
    - if both sides are dicts → ``dict.update()`` (sub‑keys override, rest kept)
    - otherwise → replace the default value outright

    A missing or unreadable file is silently ignored (defaults are returned).
    A file that exists but contains invalid JSON prints a warning to stderr
    and falls back to defaults.
    """
    cfg = copy.deepcopy(DEFAULT_CFG)
    resolved = path if path is not None else DEFAULT_CONFIG_PATH

    if not os.path.exists(resolved):
        return cfg

    try:
        with open(resolved, encoding="utf-8") as fh:
            user = json.load(fh)
    except Exception as exc:
        print(f"Warning: cannot load config '{resolved}': {exc}", file=sys.stderr)
        return cfg

    for k, v in user.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v

    return cfg


# ── Pure BPM helpers (no side‑effects, easy to unit‑test) ─────────────────────
def clamp_bpm(bpm: float, cfg: dict) -> float:
    """
    Clamp *bpm* to the [min_bpm, max_bpm] range defined in *cfg*.

    >>> clamp_bpm(10.0, {"min_bpm": 20.0, "max_bpm": 300.0})
    20.0
    >>> clamp_bpm(400.0, {"min_bpm": 20.0, "max_bpm": 300.0})
    300.0
    >>> clamp_bpm(120.0, {"min_bpm": 20.0, "max_bpm": 300.0})
    120.0
    """
    lo = float(cfg.get("min_bpm", DEFAULT_CFG["min_bpm"]))
    hi = float(cfg.get("max_bpm", DEFAULT_CFG["max_bpm"]))
    return max(lo, min(hi, bpm))


def bpm_to_midi_value(bpm: float, cfg: dict) -> int:
    """
    Map *bpm* linearly from [min_bpm, max_bpm] → [0, 127].

    The result is clamped to the valid MIDI CC range even if *bpm* is outside
    the configured window.

    >>> bpm_to_midi_value(20.0,  {"min_bpm": 20.0, "max_bpm": 300.0})
    0
    >>> bpm_to_midi_value(300.0, {"min_bpm": 20.0, "max_bpm": 300.0})
    127
    """
    lo  = float(cfg.get("min_bpm", DEFAULT_CFG["min_bpm"]))
    hi  = float(cfg.get("max_bpm", DEFAULT_CFG["max_bpm"]))
    raw = (bpm - lo) / (hi - lo) * 127.0
    return int(max(0, min(127, round(raw))))


def midi_value_to_bpm(value: int, cfg: dict) -> float:
    """
    Map a raw MIDI CC value 0‑127 linearly to [min_bpm, max_bpm].

    >>> midi_value_to_bpm(0,   {"min_bpm": 20.0, "max_bpm": 300.0})
    20.0
    >>> midi_value_to_bpm(127, {"min_bpm": 20.0, "max_bpm": 300.0})
    300.0
    """
    lo  = float(cfg.get("min_bpm", DEFAULT_CFG["min_bpm"]))
    hi  = float(cfg.get("max_bpm", DEFAULT_CFG["max_bpm"]))
    return lo + (int(value) / 127.0) * (hi - lo)
