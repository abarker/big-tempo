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

Debug
-----
Set ``"debug": True`` in the config file to print a trace of every step to
stderr:  config loading, client construction, every send attempt, and the
resolved address + args for each message.

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
``cfg["debug"]``    – set True to enable verbose stderr tracing

Example::

    "osc": {
        "host": "127.0.0.1",
        "port": 9000,
    },
    "osc_send": {
        "on_change": {"address": "/Hydrogen/BPM", "args": ["bpm"]},
    },
    "debug": True,

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
          Reads ``cfg["osc"]`` for host/port, ``cfg["osc_send"]`` for
          trigger→message mappings, and ``cfg["debug"]`` for verbose tracing.
    """

    def __init__(self, cfg: dict) -> None:
        self.cfg     = cfg
        self._client = None
        self._warned = False

        self._dbg("OscSender.__init__: starting")
        self._dbg(f"  HAS_OSC (python-osc installed) = {HAS_OSC}")

        osc_cfg = cfg.get("osc")   # None if section absent entirely
        if osc_cfg is None:
            self._dbg("  cfg['osc'] absent → OSC disabled (dormant)")
            return

        osc_send = cfg.get("osc_send", {})
        self._dbg(f"  cfg['osc']      = {osc_cfg}")
        self._dbg(f"  cfg['osc_send'] = {osc_send}")

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
            self._dbg(f"  UDP client created → {host}:{port}  ✓")
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
        self._dbg(f"send_on_change(bpm={bpm:.3f}): client={'ready' if self._client else 'NONE'}")
        spec = self.cfg.get("osc_send", {}).get("on_change")
        if spec is None:
            self._dbg("  osc_send.on_change not configured → no-op")
            return
        self._dbg(f"  spec = {spec}")
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
            self._dbg(f"send_with_context: client is None → no-op (osc_spec={osc_spec})")
            return
        address = str(osc_spec.get("address", "/"))
        args    = self._resolve_args(osc_spec.get("args", []), bpm, raw)
        self._dbg(f"send_with_context: address={address!r}  resolved_args={args}")
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
            if not args:
                self._dbg(f"  _send: {address!r}  (no args)")
                self._client.send_message(address, None)
            elif len(args) == 1:
                self._dbg(f"  _send: {address!r}  arg={args[0]!r}")
                self._client.send_message(address, args[0])
            else:
                self._dbg(f"  _send: {address!r}  args={args!r}")
                self._client.send_message(address, args)
            self._dbg("  _send: OK")
        except Exception as exc:
            if not self._warned:
                print(f"OSC send error: {exc}", file=sys.stderr)
                self._warned = True

    def _dbg(self, msg: str) -> None:
        """Print *msg* to stderr when debug mode is enabled."""
        if self.cfg.get("debug", False):
            print(f"[osc] {msg}", file=sys.stderr, flush=True)
