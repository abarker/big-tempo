"""
midi.py – MIDI I/O via mididings, running in a background daemon thread.

Design
------
* ``MidiHandler`` is constructed on the tkinter main thread and handed a
  reference to the root widget so it can schedule callbacks with
  ``root.after(0, …)``.  This keeps all tkinter calls on the main thread.

* mididings itself is imported lazily inside ``_run()`` so that importing
  this module on a machine without mididings installed does not raise.

* ``send_bpm()`` is safe to call from the main thread at any time; it
  no‑ops until the background engine has confirmed it is ready.
"""

import sys
import threading

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
    on_receive : callable(action: str, amount: float, raw: int)
                 Called on the tkinter main thread for each matched CC event.
                 action – ``'up'`` | ``'down'`` | ``'set'``
                 amount – configured BPM delta (for up/down); 0.0 for set
                 raw    – raw 0‑127 MIDI CC value
    """

    def __init__(self, cfg: dict, root, on_receive):
        self.cfg        = cfg
        self.root       = root
        self.on_receive = on_receive
        self._started   = threading.Event()

    # ── Public API ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        """Spawn the mididings thread. Silent no‑op when mididings is absent."""
        if not HAS_MIDIDINGS:
            print("mididings not found – MIDI disabled.", file=sys.stderr)
            return
        t = threading.Thread(target=self._run, daemon=True, name="mididings")
        t.start()

    def send_bpm(self, bpm: float) -> None:
        """
        Encode *bpm* as a MIDI CC value and fire it on the configured output.

        No‑op when mididings is absent or the engine thread has not yet
        finished starting up.
        """
        if not HAS_MIDIDINGS or not self._started.is_set():
            return
        send_cfg = self.cfg.get("send", {}).get("on_change")
        if not send_cfg:
            return

        cc      = int(send_cfg.get("cc",      30))
        channel = int(send_cfg.get("channel",  1))
        value   = bpm_to_midi_value(bpm, self.cfg)

        try:
            from mididings import engine            # type: ignore[import]
            from mididings.event import CtrlEvent   # type: ignore[import]
            engine.output_event(
                CtrlEvent(port=1, channel=channel, ctrl=cc, value=value)
            )
        except Exception as exc:
            print(f"MIDI send error: {exc}", file=sys.stderr)

    # ── Receive routing (mididings callback thread) ────────────────────────────
    def _handle_ctrl(self, ev) -> None:
        """
        Called by mididings for every incoming CC event.

        Looks up the CC number in ``cfg["receive"]``, then marshals the
        decoded action back to the tkinter thread via ``root.after(0, …)``.
        """
        key     = f"CC{ev.ctrl}"
        receive = self.cfg.get("receive", {})
        if key not in receive:
            return
        spec   = receive[key]
        action = spec.get("action", "")
        amount = float(spec.get("amount", 1.0))
        raw    = int(ev.value)
        self.root.after(
            0,
            lambda a=action, m=amount, r=raw: self.on_receive(a, m, r),
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
        self._started.set()   # signal that config is committed and send_bpm() works
        mrun(patch)           # blocks until the process exits
