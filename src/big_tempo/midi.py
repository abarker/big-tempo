"""
midi.py – MIDI I/O via mididings, running in a background daemon thread.

Design
------
* ``MidiHandler`` is constructed on the tkinter main thread and handed a
  reference to the root widget so it can schedule callbacks with
  ``root.after(0, …)``.  This keeps all tkinter calls on the main thread.

* mididings itself is imported lazily inside ``_run()`` so that importing
  this module on a machine without mididings installed does not raise.

* ``send_with_context()`` is safe to call from the main thread at any time;
  it no-ops until the engine confirms it is ready.

Send value tokens
-----------------
Inside a ``"send"`` action spec the ``"value"`` field controls what CC data
byte is transmitted.  Supported tokens (mirrors the OSC ``"args"`` convention):

``"bpm"``       – current BPM mapped linearly to 0–127
``"raw"``       – pass the incoming CC value straight through (0–127)
``"rolling"``   – 127 when transport started, 0 when stopped
<int 0–127>     – fixed literal value

Config layout
-------------
Send actions live in ``cfg["send"]``, keyed by trigger name.  Each entry is a
list of action dicts; MIDI actions carry ``"send": "MIDI"``::

    "send": {
        "on_change": [
            {"send": "MIDI", "cc": 30, "channel": 1, "value": "bpm"},
        ],
    },

Per-receive sends live inside the receive entry as a unified ``"send"`` list::

    "receive": {
        "CC26": {"action": "midi_only",
                 "send": [{"send": "MIDI", "cc": 35, "channel": 1, "value": 127}]},
        "CC20": {"action": "up", "amount": 1.0,
                 "send": [{"send": "MIDI", "cc": 36, "channel": 1, "value": "raw"}]},
    },
"""

import sys
import queue
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
    root       : tkinter root widget (accepted for API compatibility; no longer
                 used internally – events are queued instead of scheduled via
                 ``root.after``)
    on_receive : callable(action, amount, raw, send_specs)
                 Called on the tkinter main thread for each matched CC event.
                 The caller must drain the queue by calling ``drain()`` and
                 invoking this callback for each returned tuple.
                 action     – ``'up'`` | ``'down'`` | ``'set'`` | ``'list_append'``
                              | ``'list_next'`` | ``'list_clear'``
                              | ``'osc_only'`` | ``'midi_only'``
                 amount     – configured BPM delta (for up/down); 0.0 otherwise
                 raw        – raw 0–127 MIDI CC value
                 send_specs – list of action dicts from the receive entry's
                              ``"send"`` key, or ``[]`` if absent
    """

    def __init__(self, cfg: dict, root, on_receive):
        self.cfg          = cfg
        self.root         = root   # retained for API compatibility
        self.on_receive   = on_receive
        self._started     = threading.Event()
        self._warned_keys: set = set()
        self._queue: queue.SimpleQueue = queue.SimpleQueue()

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
                    ``"send"``    – type discriminator (ignored here; handled upstream)
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
                    f"Warning: MIDI send spec for CC {midi_spec.get('cc', '?')} "
                    f"has no 'value' key – send skipped.\n"
                    f"  Add one of: \"value\": \"bpm\"  |  \"value\": \"raw\"  "
                    f"|  \"value\": \"rolling\"  |  \"value\": <int 0-127>",
                    file=sys.stderr,
                )
            return
        cc      = int(midi_spec.get("cc",      30))
        channel = int(midi_spec.get("channel",  1))
        value   = self._resolve_value(midi_spec["value"], bpm, raw, rolling)
        self._dbg(f"send_with_context: CC{cc}  ch={channel}  value={value}")
        try:
            from mididings import engine            # type: ignore[import]
            from mididings.event import CtrlEvent   # type: ignore[import]
            engine.output_event(
                CtrlEvent(port=1, channel=channel, ctrl=cc, value=value)
            )
        except Exception as exc:
            print(f"MIDI send error: {exc}", file=sys.stderr)

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

    def drain(self) -> list:
        """
        Return all pending MIDI events as a list of
        ``(action, amount, raw, send_specs)`` tuples and clear the queue.

        Call this from the main thread on every update tick (e.g. at the top
        of ``_update_loop``) before processing JACK transport state.
        """
        events = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    # ── Receive routing (mididings callback thread) ────────────────────────────

    def _handle_ctrl(self, ev) -> None:
        """
        Called by mididings for every incoming CC event.

        Looks up the CC number in ``cfg["receive"]``, extracts the action and
        unified send list, then puts a tuple onto ``_queue`` for the main
        thread to pick up via ``drain()``.

        **Threading note**: this method does *not* run in the JACK process
        callback.  ``_run()`` configures ``backend="jack"``, not ``"jack-rt"``,
        and the patch uses ``Call()``, which mididings dispatches
        asynchronously: the C++ side pushes the event onto a lock-free
        ringbuffer that a plain ``boost::thread`` (``PythonCaller::
        async_thread``, no realtime scheduling attributes) drains.  On
        overflow that ringbuffer drops events rather than blocking, so
        nothing here can exert back-pressure on the RT path.

        Consequence: the ``_dbg`` call below is *not* an xrun hazard, and this
        method is not on a hard-realtime deadline.  It does, however, hold the
        GIL for its whole duration, so a slow write here stalls the Tk main
        loop and OSC sends -- latency, not xruns.

        ``queue.SimpleQueue.put_nowait`` is still the right handoff: it keeps
        Tcl interpreter calls off this thread, which the previous
        ``root.after(0, …)`` approach did not.

        (Contrast ``midi_event_remapper``, which start.py launches with
        ``--jack-rt`` and whose stdout is deliberately block-buffered for
        exactly the reason wrongly attributed here.)
        """
        key     = f"CC{ev.ctrl}"
        receive = self.cfg.get("receive", {})
        if key not in receive:
            return
        spec       = receive[key]
        action     = spec.get("action", "")
        amount     = float(spec.get("amount", 1.0))
        raw        = int(ev.value)
        send_specs = spec.get("send", [])
        self._dbg(
            f"CC{ev.ctrl}={ev.value} → action={action!r}"
            f"  amount={amount}  sends={len(send_specs)}"
        )
        self._queue.put_nowait((action, amount, raw, send_specs))

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
