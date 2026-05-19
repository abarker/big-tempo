"""
config.py – configuration defaults, loader, and pure BPM arithmetic helpers.

All functions in this module are free of tkinter / JACK / mididings so they
can be imported and tested on any machine.
"""

import ast
import copy
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
    # Unified send list: maps trigger names to a list of action dicts.
    # Each action dict must have a "send" key of "MIDI" or "OSC".
    # OSC actions carry "host", "port", and "address" inline.
    # Example:
    #   "send": {
    #       "on_change": [
    #           {"send": "MIDI", "cc": 30, "channel": 1, "value": "bpm"},
    #           {"send": "OSC",  "host": "127.0.0.1", "port": 9000,
    #            "address": "/Hydrogen/BPM", "args": ["bpm"]},
    #       ],
    #   }
    "send":  {},
    "debug": False,
    "quantize":      None,
    "quantize_jack": False,
}

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/big-tempo/config.py")


# ── Loader ─────────────────────────────────────────────────────────────────────
def load_config(path: Optional[str] = None) -> dict:
    """
    Return a config dict merged from built-in defaults and the Python dict
    literal file at *path* (default: ``~/.config/big-tempo/config.py``).

    The config file must contain a single Python dict literal – the same
    syntax as a Python ``dict`` expression, with full support for ``#``
    line comments.  It is parsed with ``ast.literal_eval``, which accepts
    only data literals (strings, numbers, booleans, ``None``, lists, dicts)
    and cannot execute arbitrary code.

    Example config.py::

        {
            "min_bpm": 40.0,            # raise floor for this gig
            "receive": {
                "CC20": {"action": "up",   "amount": 1.0},
                "CC21": {"action": "down", "amount": 1.0},
            },
            "send": {
                "on_change": [
                    {"send": "MIDI", "cc": 30, "channel": 1, "value": "bpm"},
                    {"send": "OSC",  "host": "127.0.0.1", "port": 9000,
                     "address": "/Hydrogen/BPM", "args": ["bpm"]},
                ],
            },
        }

    Merge strategy: deep-copy the defaults, then for every top-level key
    present in the user file:

    - if both sides are dicts → ``dict.update()`` (sub-keys override, rest kept)
    - otherwise → replace the default value outright

    A missing file is silently ignored (defaults are returned).
    A file that exists but is malformed prints a warning to stderr and
    falls back to defaults.
    """
    cfg = copy.deepcopy(DEFAULT_CFG)
    resolved = path if path is not None else DEFAULT_CONFIG_PATH

    if not os.path.exists(resolved):
        return cfg

    try:
        with open(resolved, encoding="utf-8") as fh:
            source = fh.read()
        user = ast.literal_eval(source)
        if not isinstance(user, dict):
            raise TypeError(
                f"config file must contain a dict literal, got {type(user).__name__}"
            )
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


def quantize_bpm(bpm: float, cfg: dict) -> float:
    """
    Snap *bpm* to the nearest multiple of ``cfg["quantize"]``.

    Returns *bpm* unchanged when ``cfg["quantize"]`` is ``None``, ``0``, or
    absent (quantization disabled).

    The step can be any positive float:

    * ``1.0``  → integer BPM  (120.0, 121.0, …)
    * ``0.5``  → half-BPM     (120.0, 120.5, 121.0, …)
    * ``0.25`` → quarter-BPM  (120.0, 120.25, 120.5, …)

    Quantization is applied *before* clamping when used together, but the
    helper itself does not clamp – compose with ``clamp_bpm`` as needed.

    >>> quantize_bpm(120.3, {"quantize": 1.0})
    120.0
    >>> quantize_bpm(120.7, {"quantize": 1.0})
    121.0
    >>> quantize_bpm(120.3, {"quantize": 0.5})
    120.5
    >>> quantize_bpm(120.3, {"quantize": None})
    120.3
    """
    step = cfg.get("quantize")
    if not step:          # None, 0, False → disabled
        return bpm
    step = float(step)
    if step <= 0.0:
        return bpm
    return round(bpm / step) * step


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
