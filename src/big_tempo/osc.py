"""
osc.py – general-purpose OSC sender for big-tempo.

Design
------
``OscSender`` maintains a pool of UDP OSC clients keyed by ``(host, port)``
target.  Clients are created on first use and reused for every subsequent
send to the same target.  This allows a single ``"send"`` action list to fan
out to multiple OSC destinations with no setup overhead at send time.

``send_with_context(spec, bpm, raw, rolling)``
    Read ``"host"``, ``"port"``, and ``"address"`` directly from *spec*;
    resolve the ``"args"`` list against the live context; then fire the
    message via the matching pool entry.

Because connection details travel with each action spec there is no global
``"osc"`` config block.  The pool is populated lazily and a fresh
``OscSender`` is created on every config hot-reload (cheap – no sockets
are opened until the first send).

Dependency
----------
``python-osc`` is a required runtime dependency listed in ``pyproject.toml``.
The import is wrapped in a try/except so that the module can still be
imported on a machine where the library is absent (e.g. a CI environment
that only runs config/BPM tests), but OSC output will be disabled and a
warning will be printed.

Arg tokens
----------
Inside an ``"args"`` list, string tokens are substituted at send time:

``"bpm"``     – current BPM as a float
``"raw"``     – raw incoming CC value 0-127 as an int
``"rolling"`` – 1 when transport started, 0 when stopped
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
    Multi-destination OSC sender with a lazy (host, port) pool.

    Parameters
    ----------
    cfg : full application config dict.
          Used only for the ``"debug"`` flag; OSC connection details are now
          read from individual action specs at send time.
    """

    def __init__(self, cfg: dict) -> None:
        self.cfg    = cfg
        self._pool: dict[tuple[str, int], Any] = {}   # (host, port) → client | None
        self._warned = False

        self._dbg("OscSender.__init__")
        self._dbg(f"  HAS_OSC (python-osc installed) = {HAS_OSC}")

        if not HAS_OSC:
            print(
                "Warning: python-osc not installed – OSC output disabled.\n"
                "  pip install python-osc",
                file=sys.stderr,
            )

    # ── Public API ──────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """True when the python-osc library is available."""
        return HAS_OSC

    def send_with_context(
        self,
        spec: dict,
        bpm: float,
        raw: int,
        rolling: int = 0,
    ) -> None:
        """
        Resolve *spec* against the live *bpm* / *raw* / *rolling* context
        and send the OSC message.

        Parameters
        ----------
        spec : dict with keys:
               ``"host"``    – target hostname / IP  (default ``"127.0.0.1"``)
               ``"port"``    – target UDP port       (default ``9000``)
               ``"address"`` – OSC address string    (required)
               ``"args"``    – list of arg tokens / literals (optional)
        bpm      : current BPM value (substituted for ``"bpm"`` tokens)
        raw      : raw CC value 0-127  (substituted for ``"raw"`` tokens)
        rolling  : 1 when transport started, 0 when stopped
        """
        if not HAS_OSC:
            return
        host    = str(spec.get("host", DEFAULT_HOST))
        port    = int(spec.get("port", DEFAULT_PORT))
        address = str(spec.get("address", "/"))
        args    = self._resolve_args(spec.get("args", []), bpm, raw, rolling)
        self._dbg(
            f"send_with_context: {host}:{port}  address={address!r}"
            f"  resolved_args={args}  rolling={rolling}"
        )
        client = self._get_client(host, port)
        if client is None:
            return
        self._send(client, address, args)

    # ── Internals ───────────────────────────────────────────────────────────────

    def _get_client(self, host: str, port: int):
        """
        Return the cached UDP client for *(host, port)*, creating it on first
        use.  Stores ``None`` on failure so we don't retry a broken target.
        """
        key = (host, port)
        if key not in self._pool:
            try:
                from pythonosc.udp_client import SimpleUDPClient  # type: ignore[import]
                self._pool[key] = SimpleUDPClient(host, port)
                self._dbg(f"  new UDP client → {host}:{port}  ✓")
            except Exception as exc:
                print(
                    f"Warning: cannot create OSC client ({host}:{port}): {exc}",
                    file=sys.stderr,
                )
                self._pool[key] = None
        return self._pool[key]

    def _resolve_args(
        self,
        template: list,
        bpm: float,
        raw: int,
        rolling: int = 0,
    ) -> list[Any]:
        """
        Substitute token strings; pass all other values through unchanged.

        Tokens:
          ``"bpm"``     – current BPM as float
          ``"raw"``     – incoming CC value 0-127 as int
          ``"rolling"`` – 1 when transport started, 0 when stopped
          any other   – passed through unchanged
        """
        out = []
        for token in template:
            if token == "bpm":
                out.append(float(bpm))
            elif token == "raw":
                out.append(int(raw))
            elif token == "rolling":
                out.append(int(rolling))
            else:
                out.append(token)
        return out

    def _send(self, client, address: str, args: list) -> None:
        """Low-level UDP send.  Errors produce one warning then are suppressed."""
        try:
            if not args:
                self._dbg(f"  _send: {address!r}  (no args)")
                client.send_message(address, None)
            elif len(args) == 1:
                self._dbg(f"  _send: {address!r}  arg={args[0]!r}")
                client.send_message(address, args[0])
            else:
                self._dbg(f"  _send: {address!r}  args={args!r}")
                client.send_message(address, args)
            self._dbg("  _send: OK")
        except Exception as exc:
            if not self._warned:
                print(f"OSC send error: {exc}", file=sys.stderr)
                self._warned = True

    def _dbg(self, msg: str) -> None:
        """Print *msg* to stderr when debug mode is enabled."""
        if self.cfg.get("debug", False):
            print(f"[osc] {msg}", file=sys.stderr, flush=True)
