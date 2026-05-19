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

# ── Validation constants ───────────────────────────────────────────────────────
VALID_ACTIONS = frozenset({
    "up", "down", "set",
    "list_append", "list_next", "list_clear",
    "osc_only", "midi_only",
})

VALID_TRIGGERS = frozenset({
    "on_change", "on_quantize",
    "transport_start", "transport_stop", "transport_toggle",
})

VALID_SEND_TYPES  = frozenset({"MIDI", "OSC"})
VALID_VALUE_TOKENS = frozenset({"bpm", "raw", "rolling"})

# Keys that existed in the old config format and are now ignored.
LEGACY_KEYS = frozenset({"midi_send", "osc_send", "osc"})

import re as _re
_CC_KEY = _re.compile(r'^CC(\d+)$')


# ── Validation ─────────────────────────────────────────────────────────────────
def validate_config(cfg: dict) -> list[str]:
    """
    Inspect *cfg* for semantic problems and return a list of human-readable
    warning strings.  An empty list means no problems were found.

    Validation is non-fatal: the caller decides what to do with the warnings
    (typically print them to stderr).  The config dict is never modified.

    Checks performed
    ----------------
    * Legacy keys (``midi_send``, ``osc_send``, ``osc``) that no longer have
      any effect in the new unified ``send`` format.
    * ``min_bpm`` / ``max_bpm`` ordering and type.
    * ``quantize`` is a positive number or ``None``.
    * ``buttons.increment`` is a positive number.
    * ``receive`` entries: key format, recognised action names.
    * ``send`` entries: recognised trigger names, list shape, ``"send"``
      discriminator, required fields for MIDI (cc, channel, value) and OSC
      (host, port, address).
    * Per-receive ``"send"`` lists: same MIDI / OSC field checks.
    """
    warnings: list[str] = []
    _val_legacy_keys(cfg, warnings)
    _val_scalars(cfg, warnings)
    _val_receive(cfg.get("receive", {}), warnings)
    _val_send_section(cfg.get("send", {}), warnings)
    return warnings


# ── Private helpers ────────────────────────────────────────────────────────────

def _val_legacy_keys(cfg: dict, out: list) -> None:
    for key in sorted(LEGACY_KEYS & cfg.keys()):
        out.append(
            f"'{key}' is no longer used – migrate to the unified 'send' list format"
        )


def _val_scalars(cfg: dict, out: list) -> None:
    min_bpm = cfg.get("min_bpm")
    max_bpm = cfg.get("max_bpm")
    if min_bpm is not None and max_bpm is not None:
        if not isinstance(min_bpm, (int, float)):
            out.append(f"'min_bpm' must be a number (got {min_bpm!r})")
        elif not isinstance(max_bpm, (int, float)):
            out.append(f"'max_bpm' must be a number (got {max_bpm!r})")
        elif float(min_bpm) >= float(max_bpm):
            out.append(
                f"'min_bpm' ({min_bpm}) must be less than 'max_bpm' ({max_bpm})"
            )

    q = cfg.get("quantize")
    if q is not None and q is not False:
        if not isinstance(q, (int, float)) or float(q) <= 0:
            out.append(
                f"'quantize' must be a positive number or None (got {q!r})"
            )

    buttons = cfg.get("buttons", {})
    if isinstance(buttons, dict):
        inc = buttons.get("increment")
        if inc is not None and (not isinstance(inc, (int, float)) or inc <= 0):
            out.append(
                f"'buttons.increment' must be a positive number (got {inc!r})"
            )


def _val_receive(receive: object, out: list) -> None:
    if not isinstance(receive, dict):
        out.append("'receive' must be a dict")
        return
    for key, entry in receive.items():
        loc = f"receive[{key!r}]"
        m = _CC_KEY.match(str(key))
        if not m:
            out.append(f"{loc}: key must be of the form 'CC<number>' (e.g. 'CC20')")
            continue
        cc_num = int(m.group(1))
        if not 0 <= cc_num <= 127:
            out.append(f"{loc}: CC number {cc_num} is out of range 0–127")
        if not isinstance(entry, dict):
            out.append(f"{loc}: entry must be a dict")
            continue
        action = entry.get("action")
        if action is None:
            out.append(f"{loc}: missing required 'action' key")
        elif action not in VALID_ACTIONS:
            out.append(
                f"{loc}: unknown action {action!r} – "
                f"valid actions: {', '.join(sorted(VALID_ACTIONS))}"
            )
        send_list = entry.get("send")
        if send_list is not None:
            if not isinstance(send_list, list):
                out.append(f"{loc}['send']: must be a list of action dicts")
            else:
                for i, spec in enumerate(send_list):
                    _val_send_action(f"{loc}['send'][{i}]", spec, out)


def _val_send_section(send: object, out: list) -> None:
    if not isinstance(send, dict):
        out.append("'send' must be a dict")
        return
    for trigger, actions in send.items():
        loc = f"send[{trigger!r}]"
        if trigger not in VALID_TRIGGERS:
            out.append(
                f"{loc}: unknown trigger – "
                f"valid triggers: {', '.join(sorted(VALID_TRIGGERS))}"
            )
        if not isinstance(actions, list):
            out.append(
                f"{loc}: value must be a list of action dicts "
                f"(got {type(actions).__name__} – old single-dict format?)"
            )
            continue
        for i, spec in enumerate(actions):
            _val_send_action(f"{loc}[{i}]", spec, out)


def _val_send_action(loc: str, spec: object, out: list) -> None:
    if not isinstance(spec, dict):
        out.append(f"{loc}: action must be a dict (got {type(spec).__name__})")
        return
    send_type = spec.get("send")
    if send_type is None:
        out.append(f"{loc}: missing required 'send' key (expected 'MIDI' or 'OSC')")
        return
    if send_type not in VALID_SEND_TYPES:
        out.append(
            f"{loc}: unknown send type {send_type!r} – expected 'MIDI' or 'OSC'"
        )
        return
    if send_type == "MIDI":
        _val_midi_action(loc, spec, out)
    else:
        _val_osc_action(loc, spec, out)


def _val_midi_action(loc: str, spec: dict, out: list) -> None:
    cc = spec.get("cc")
    if cc is None:
        out.append(f"{loc}: MIDI send missing required 'cc' key")
    elif not isinstance(cc, int) or not 0 <= cc <= 127:
        out.append(f"{loc}: MIDI 'cc' must be an integer 0–127 (got {cc!r})")

    channel = spec.get("channel")
    if channel is None:
        out.append(f"{loc}: MIDI send missing required 'channel' key")
    elif not isinstance(channel, int) or not 1 <= channel <= 16:
        out.append(f"{loc}: MIDI 'channel' must be an integer 1–16 (got {channel!r})")

    if "value" not in spec:
        out.append(
            f"{loc}: MIDI send missing required 'value' key – "
            f"use one of: {', '.join(sorted(VALID_VALUE_TOKENS))}, or an integer 0–127"
        )
    else:
        value = spec["value"]
        if isinstance(value, str):
            if value not in VALID_VALUE_TOKENS:
                out.append(
                    f"{loc}: unknown MIDI 'value' token {value!r} – "
                    f"valid tokens: {', '.join(sorted(VALID_VALUE_TOKENS))}"
                )
        elif isinstance(value, int):
            if not 0 <= value <= 127:
                out.append(f"{loc}: MIDI 'value' {value} is out of range 0–127")
        else:
            out.append(
                f"{loc}: MIDI 'value' must be a string token or integer 0–127 "
                f"(got {value!r})"
            )


def _val_osc_action(loc: str, spec: dict, out: list) -> None:
    host = spec.get("host")
    if host is None:
        out.append(f"{loc}: OSC send missing required 'host' key")
    elif not isinstance(host, str):
        out.append(f"{loc}: OSC 'host' must be a string (got {host!r})")

    port = spec.get("port")
    if port is None:
        out.append(f"{loc}: OSC send missing required 'port' key")
    elif not isinstance(port, int) or not 1 <= port <= 65535:
        out.append(f"{loc}: OSC 'port' must be an integer 1–65535 (got {port!r})")

    address = spec.get("address")
    if address is None:
        out.append(f"{loc}: OSC send missing required 'address' key")
    elif not isinstance(address, str) or not address.startswith("/"):
        out.append(
            f"{loc}: OSC 'address' must be a string starting with '/' (got {address!r})"
        )

    args = spec.get("args")
    if args is not None and not isinstance(args, list):
        out.append(f"{loc}: OSC 'args' must be a list (got {type(args).__name__})")


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

    for warning in validate_config(cfg):
        print(f"Config warning: {warning}", file=sys.stderr)

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
