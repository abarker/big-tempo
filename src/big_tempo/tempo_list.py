"""
tempo_list.py – a simple cyclic tempo list.

This module is intentionally free of tkinter, JACK, and mididings so it can
be imported and unit-tested on any machine.

Workflow
--------
1. While performing, send ``list_append`` at any tempo to save it.
2. Send ``list_next`` to step through the saved tempos cyclically; each step
   immediately applies the recalled tempo as the new BPM.
3. Send ``list_clear`` when the set is over and you want a clean slate.

State diagram (index shown relative to list)::

    empty list           → next() → no-op (returns None)
    [120]                → next() → 120  (index 0)
    [120, 140]           → next() → 140  (index 1)
    [120, 140, 160]      → next() → 120  (wraps to index 0)
    clear()              → [] index=-1
"""

from __future__ import annotations


class TempoList:
    """
    A mutable, cyclic list of BPM values.

    Attributes are intentionally exposed (not name-mangled) so tests can
    inspect state directly.

    Parameters
    ----------
    None – use ``append()``, ``next()``, and ``clear()`` to manage content.
    """

    def __init__(self) -> None:
        self._tempos: list[float] = []
        self._index:  int         = -1   # -1 means "before the first entry"

    # ── Mutations ──────────────────────────────────────────────────────────────
    def append(self, bpm: float) -> None:
        """
        Add *bpm* to the end of the list.

        The current position is not changed; the next call to ``next()`` will
        still advance from wherever the pointer currently sits.

        >>> tl = TempoList(); tl.append(120.0); list(tl) == [120.0]
        True
        """
        self._tempos.append(float(bpm))

    def next(self) -> float | None:
        """
        Advance the pointer by one step (wrapping cyclically) and return the
        BPM at the new position.

        Returns ``None`` and leaves the list unchanged when the list is empty.

        >>> tl = TempoList()
        >>> tl.next() is None
        True
        >>> tl.append(120.0); tl.append(140.0)
        >>> tl.next()
        120.0
        >>> tl.next()
        140.0
        >>> tl.next()   # wraps
        120.0
        """
        if not self._tempos:
            return None
        self._index = (self._index + 1) % len(self._tempos)
        return self._tempos[self._index]

    def clear(self) -> None:
        """
        Remove all stored tempos and reset the pointer.

        >>> tl = TempoList(); tl.append(120.0); tl.clear(); len(tl) == 0
        True
        """
        self._tempos = []
        self._index  = -1

    # ── Read-only views ────────────────────────────────────────────────────────
    @property
    def tempos(self) -> list[float]:
        """A shallow copy of the stored BPM values (safe to iterate externally)."""
        return list(self._tempos)

    @property
    def index(self) -> int:
        """Current pointer position.  ``-1`` when the list is empty or freshly cleared."""
        return self._index

    @property
    def current(self) -> float | None:
        """BPM at the current pointer position, or ``None`` if the list is empty."""
        if not self._tempos or self._index < 0:
            return None
        return self._tempos[self._index]

    # ── Standard container interface ───────────────────────────────────────────
    def __len__(self) -> int:
        return len(self._tempos)

    def __iter__(self):
        return iter(self._tempos)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"TempoList(tempos={self._tempos!r}, index={self._index})"
        )
