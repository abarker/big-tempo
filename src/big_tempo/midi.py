"""
midi.py – MIDI I/O via mididings, running in a background daemon thread.

Design
------
* ``MidiHandler`` is constructed on the tkinter main thread and handed a
  reference to the root widget so it can schedule callbacks with
  ``root.after(0, …)``.  This keeps all tkinter calls on the main thread.

* mididings itself is imported lazily inside ``_run()`` so that importing
  this module on a machine without mididings installed does not raise.

* ``send_on_change()`` / ``send_with_context()`` are safe to call from the
  main thread at any time; they no-op until the engine confirms it is ready.

Send value tokens
-----------------
Inside a ``midi_send`` spec the ``"value"`` field controls what CC data byte
is transmitted.  Supported tokens (mirrors the OSC ``"args"`` convention):

``"bpm"``       – current BPM mapped linearly to 0–127 (default)
``"raw"``       – pass the incoming CC value straight through (0–127)
<int 0–127>     – fixed literal value

Config layout
-------------
``cfg["midi_send"]`` – trigger → message mappings::

    "midi_send": {
        "on_change": {"cc": 30, "channel": 1},             # value defaults to "bpm"
        "on_change": {"cc": 30, "channel": 1, "value": "bpm"},  # explicit
    },

Per-receive sends live inside the receive entry::

    "receive": {
        "CC26": {"action": "midi_only",
                 "midi_send": {"cc": 35, "channel": 1, "value": 127}},
        "CC20": {"action": "up", "amount": 1.0,
                 "midi_send": {"cc": 36, "channel": 1, "value": "raw"}},
    },
"""

import sys
import threading
from typing import Any

# Presence check only – actual mididings API is imported lazily.
try:
    import mididings  # noqa: F401
    HAS_MIDIDINGS = True
except ImportError:
    HAS_MIDIDINGS = False

from big_tempo.config import bpm_to_midi_value


class MidiHandler:
    """
    Wraps a mididings JACK MIDI engine in a daemon thread.

    Parameters
    ----------
    cfg        : full application config dict
    root       : tkinter root widget (used only for ``root.after()``)
    on_receive : callable(action, amount, raw, osc_spec, midi_spec)
                 Called on the tkinter main thread for each matched CC event.
                 action    – ``'up'`` | ``'down'`` | ``'set'`` | ``'list_append'``
                             | ``'list_next'`` | ``'list_clear'``
                             | ``'osc_only'`` | ``'midi_only'``
                 amount    – configured BPM delta (for up/down); 0.0 otherwise
                 raw       – raw 0–127 MIDI CC value
                 osc_spec  – ``"osc_send"`` sub-dict from receive entry, or None
                 midi_spec – ``"midi_send"`` sub-dict from receive entry, or None
    """

    def __init__(self, cfg: dict, root, on_receive):
        self.cfg          = cfg
        self.root         = root
        self.on_receive   = on_receive
        self._started     = threading.Event()
        self._warned_keys: set = set()   # tracks one-time config warnings

    # ── Public API ──────────────────────────────────────────────────────────────

    def _dbg(self, msg: str) -> None:
        """Print *msg* to stderr when debug mode is enabled."""
        if self.cfg.get("debug", False):
            print(f"[midi] {msg}", file=sys.stderr, flush=True)

    def start(self) -> None:
        """Spawn the mididings thread. Silent no-op when mididings is absent."""
        if not HAS_MIDIDINGS:
            print("mididings not found – MIDI disabled.", file=sys.stderr)
            return
        t = threading.Thread(target=self._run, daemon=True, name="mididings")
        t.start()

    def send_on_change(self, bpm: float) -> None:
        """
        Fire the ``midi_send.on_change`` message (if configured).

        Called by ``_user_set_bpm()`` on every user-initiated BPM change.
        ``raw`` is meaningless in this context and is passed as 0.
        """
        self._dbg(f"send_on_change(bpm={bpm:.3f}): started={self._started.is_set()}")
        spec = self.cfg.get("midi_send", {}).get("on_change")
        if spec is None:
            self._dbg("  midi_send.on_change not configured → no-op")
            return
        self._dbg(f"  spec = {spec}")
        self.send_with_context(spec, bpm=bpm, raw=0)

    def send_with_context(
        self,
        midi_spec: dict,
        bpm: float,
        raw: int,
        rolling: int = 0,
    ) -> None:
        """
        Resolve *midi_spec* against the live *bpm* / *raw* context and send a
        MIDI CC event.

        Parameters
        ----------
        midi_spec : dict with keys:
                    ``"cc"``      – controller number (required)
                    ``"channel"`` – MIDI channel 1-16 (default 1)
                    ``"value"``   – token or literal (**required**; no default).
                                  Omitting it prints a warning and skips the send.
        bpm       : current BPM (used to resolve ``"bpm"`` token)
        raw       : incoming CC value 0-127 (used to resolve ``"raw"`` token)
        """
        if not HAS_MIDIDINGS or not self._started.is_set():
            return
        if "value" not in midi_spec:
            # Warn once per spec (use the cc number as the key).
            key = f"missing_value_cc{midi_spec.get('cc', '?')}"
            if key not in self._warned_keys:
                self._warned_keys.add(key)
                print(
                    f"Warning: midi_send spec for CC {midi_spec.get('cc', '?')} "
                    f"has no 'value' key – send skipped.\n"
                    f"  Add one of: \"value\": \"bpm\"  |  \"value\": \"raw\"  "
                    f"|  \"value\": \"rolling\"  |  \"value\": <int 0-127>",
                    file=sys.stderr,
                )
            return
        cc      = int(midi_spec.get("cc",      30))
        channel = int(midi_spec.get("channel",  1))
        value   = self._resolve_value(midi_spec["value"], bpm, raw, rolling)
        try:
            from mididings import engine            # type: ignore[import]
            from mididings.event import CtrlEvent   # type: ignore[import]
            engine.output_event(
                CtrlEvent(port=1, channel=channel, ctrl=cc, value=value)
            )
        except Exception as exc:
            print(f"MIDI send error: {exc}", file=sys.stderr)

    # kept for backwards-compatibility with any external code that called it
    def send_bpm(self, bpm: float) -> None:
        """Alias for ``send_on_change(bpm)``."""
        self.send_on_change(bpm)

    # ── Value resolution ────────────────────────────────────────────────────────

    def _resolve_value(self, token: Any, bpm: float, raw: int, rolling: int = 0) -> int:
        """
        Resolve a value token to a MIDI data byte (0–127).

        ``"bpm"``     – map *bpm* linearly from min_bpm…max_bpm → 0–127
        ``"raw"``     – pass *raw* through unchanged (clamped to 0–127)
        ``"rolling"`` – 127 when transport started, 0 when stopped
        <int>         – literal value (clamped to 0–127)
        """
        if token == "bpm":
            return bpm_to_midi_value(bpm, self.cfg)
        elif token == "raw":
            return max(0, min(127, int(raw)))
        elif token == "rolling":
            return 127 if rolling else 0
        else:
            return max(0, min(127, int(token)))

    # ── Receive routing (mididings callback thread) ────────────────────────────

    def _handle_ctrl(self, ev) -> None:
        """
        Called by mididings for every incoming CC event.

        Looks up the CC number in ``cfg["receive"]``, extracts the action and
        both send specs, then marshals everything to the tkinter thread via
        ``root.after(0, …)``.
        """
        key     = f"CC{ev.ctrl}"
        receive = self.cfg.get("receive", {})
        if key not in receive:
            return
        spec      = receive[key]
        action    = spec.get("action", "")
        amount    = float(spec.get("amount", 1.0))
        raw       = int(ev.value)
        osc_spec  = spec.get("osc_send")    # None if not configured
        midi_spec = spec.get("midi_send")   # None if not configured
        self.root.after(
            0,
            lambda a=action, m=amount, r=raw, o=osc_spec, ms=midi_spec:
                self.on_receive(a, m, r, o, ms),
        )

    # ── Engine thread ───────────────────────────────────────────────────────────

    def _run(self) -> None:
        from mididings import (         # type: ignore[import]
            CTRL,
            Call,
            Filter,
            config as mconf,
            run as mrun,
        )

        midi_cfg = self.cfg.get("midi", {})
        mconf(
            backend="jack",
            client_name=midi_cfg.get("client_name", "big_tempo_midi"),
            in_ports=["in"],
            out_ports=["out"],
        )
        patch = Filter(CTRL) >> Call(self._handle_ctrl)
        self._dbg("mididings engine starting…")
        self._started.set()
        mrun(patch)
