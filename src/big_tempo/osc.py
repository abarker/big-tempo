"""
osc.py – general-purpose OSC sender for big-tempo.

Design
------
``OscSender`` wraps a single UDP OSC client (one host + port pair, taken from
``cfg["osc"]``) and exposes two public methods:

``send_with_context(osc_spec, bpm, raw)``
    Resolve the ``"args"`` list in *osc_spec* – substituting token strings
    ``"bpm"`` and ``"raw"`` with live values – then fire the message.
    Used both by the ``on_change`` trigger and per-receive ``osc_send`` specs.

``send_on_change(bpm)``
    Convenience: look up ``cfg["osc_send"]["on_change"]`` and call
    ``send_with_context`` with ``raw=0`` (raw CC is not meaningful here).

Why python-osc instead of mididings OSC
-----------------------------------------
mididings' ``mididings.extra.osc`` is designed for *receiving* OSC to
remote-control mididings itself (switching patches, etc.).  Sending arbitrary
OSC as a side-effect of a MIDI event would require a ``Call()`` wrapping a
pyliblo (C extension) send – adding a compiled dependency for no gain over
the pure-Python python-osc library.

Dependency
----------
``python-osc`` (pure Python, no C extensions)::

    pip install python-osc

Degrades gracefully when absent: all methods are callable but nothing is
transmitted and a one-time warning is printed.

Config layout
-------------
``cfg["osc"]``      – connection info (host, port)
``cfg["osc_send"]`` – trigger → message mappings

Example::

    "osc": {
        "host": "127.0.0.1",
        "port": 9000,
    },
    "osc_send": {
        "on_change": {"address": "/Hydrogen/BPM", "args": ["bpm"]},
    },

    # Per-receive OSC lives inside the receive entry:
    "receive": {
        "CC30": {"action": "osc_only",
                 "osc_send": {"address": "/Hydrogen/PLAY", "args": [1]}},
        "CC31": {"action": "up", "amount": 1.0,
                 "osc_send": {"address": "/log/up", "args": ["bpm", "raw"]}},
    },

Arg tokens
----------
Inside an ``"args"`` list, string tokens are substituted at send time:

``"bpm"``   – current BPM as a float
``"raw"``   – raw incoming CC value 0-127 as an int
any other value – passed through unchanged (int, float, str, bool)
"""

from __future__ import annotations

import sys
from typing import Any

try:
    import pythonosc.udp_client   # type: ignore[import]  # presence check only
    HAS_OSC = True
except ImportError:
    HAS_OSC = False

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9000


class OscSender:
    """
    Single-destination OSC sender.

    Parameters
    ----------
    cfg : full application config dict.
          Reads ``cfg["osc"]`` for host/port and ``cfg["osc_send"]`` for
          trigger→message mappings.
    """

    def __init__(self, cfg: dict) -> None:
        self.cfg     = cfg
        self._client = None
        self._warned = False

        osc_cfg = cfg.get("osc")   # None if section absent entirely
        if osc_cfg is None:
            return                  # no osc section → stay dormant

        if not HAS_OSC:
            print(
                "Warning: python-osc not installed – OSC output disabled.\n"
                "  pip install python-osc",
                file=sys.stderr,
            )
            return

        host = str(osc_cfg.get("host", DEFAULT_HOST))
        port = int(osc_cfg.get("port", DEFAULT_PORT))
        try:
            from pythonosc.udp_client import SimpleUDPClient  # type: ignore[import]
            self._client = SimpleUDPClient(host, port)
        except Exception as exc:
            print(
                f"Warning: cannot create OSC client ({host}:{port}): {exc}",
                file=sys.stderr,
            )

    # ── Public API ──────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """True when the OSC UDP client was created successfully."""
        return self._client is not None

    def send_on_change(self, bpm: float) -> None:
        """
        Fire the ``osc_send.on_change`` message (if configured).

        Called by ``_user_set_bpm()`` on every user-initiated BPM change.
        ``raw`` is meaningless in this context and is passed as 0.
        """
        spec = self.cfg.get("osc_send", {}).get("on_change")
        if spec:
            self.send_with_context(spec, bpm=bpm, raw=0)

    def send_with_context(
        self,
        osc_spec: dict,
        bpm: float,
        raw: int,
    ) -> None:
        """
        Resolve *osc_spec* against the live *bpm* / *raw* context and send.

        Parameters
        ----------
        osc_spec : dict with keys:
                   ``"address"`` – OSC address string (required)
                   ``"args"``    – list of arg tokens / literals (optional)
        bpm      : current BPM value (substituted for ``"bpm"`` tokens)
        raw      : raw CC value 0-127  (substituted for ``"raw"`` tokens)
        """
        if self._client is None:
            return
        address = str(osc_spec.get("address", "/"))
        args    = self._resolve_args(osc_spec.get("args", []), bpm, raw)
        self._send(address, args)

    # ── Internals ───────────────────────────────────────────────────────────────

    def _resolve_args(
        self,
        template: list,
        bpm: float,
        raw: int,
    ) -> list[Any]:
        """Substitute token strings; pass all other values through unchanged."""
        out = []
        for token in template:
            if token == "bpm":
                out.append(float(bpm))
            elif token == "raw":
                out.append(int(raw))
            else:
                out.append(token)
        return out

    def _send(self, address: str, args: list) -> None:
        """Low-level UDP send.  Errors produce one warning then are suppressed."""
        try:
            # python-osc requires a single value or a list for multiple args.
            # An empty args list means send the message with no arguments.
            if not args:
                self._client.send_message(address, None)
            elif len(args) == 1:
                self._client.send_message(address, args[0])
            else:
                self._client.send_message(address, args)
        except Exception as exc:
            if not self._warned:
                print(f"OSC send error: {exc}", file=sys.stderr)
                self._warned = True
