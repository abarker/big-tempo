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

    def replace_current(self, bpm: float) -> bool:
        """
        Overwrite the entry at the current pointer position with *bpm*.

        Returns ``True`` if the list was non-empty and the pointer was
        pointing at an entry (index ≥ 0); ``False`` otherwise (no change
        is made when the list is empty or the pointer has not advanced).

        >>> tl = TempoList()
        >>> tl.replace_current(120.0)   # empty list
        False
        >>> tl.append(100.0); tl.next()
        100.0
        >>> tl.replace_current(110.0)
        True
        >>> tl.current
        110.0
        """
        if not self._tempos or self._index < 0:
            return False
        self._tempos[self._index] = float(bpm)
        return True

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

    def set_at(self, index: int, bpm: float) -> None:
        """
        Overwrite the value at *index* without moving the pointer.

        This is the direct-index equivalent of ``replace_current()``.
        Useful for editing a specific list entry in-place (e.g. mouse-wheel
        nudge on a pill) without activating it or changing the playing tempo.

        Raises ``IndexError`` when *index* is out of range.

        >>> tl = TempoList()
        >>> tl.append(100.0); tl.append(120.0)
        >>> tl.set_at(1, 125.0)
        >>> tl.tempos
        [100.0, 125.0]
        >>> tl.index        # pointer unaffected
        -1
        """
        if not 0 <= index < len(self._tempos):
            raise IndexError(
                f"TempoList index {index} out of range for list of length "
                f"{len(self._tempos)}"
            )
        self._tempos[index] = float(bpm)

    def goto(self, index: int) -> float:
        """
        Move the pointer directly to *index* and return the BPM there.

        This is the direct-select equivalent of ``next()``: the caller gets
        the BPM value so it can apply it immediately without a separate
        ``current`` look-up.

        Raises ``IndexError`` when *index* is out of range.

        >>> tl = TempoList()
        >>> tl.append(100.0); tl.append(120.0); tl.append(140.0)
        >>> tl.goto(1)
        120.0
        >>> tl.index
        1
        """
        if not 0 <= index < len(self._tempos):
            raise IndexError(
                f"TempoList index {index} out of range for list of length "
                f"{len(self._tempos)}"
            )
        self._index = index
        return self._tempos[index]

    def remove(self, index: int) -> None:
        """
        Delete the entry at *index* and adjust the pointer.

        Pointer rules
        -------------
        * List becomes empty → pointer resets to -1.
        * Removed entry **was active** → pointer moves to what is now at
          *index* (the old "next" entry).  If the removed entry was the last
          one, the pointer wraps to 0 (consistent with ``next()`` wrapping).
        * Removed entry was **before** the active entry → pointer decrements
          by 1 so the same entry remains active.
        * Removed entry was **after** the active entry → pointer unchanged.

        Raises ``IndexError`` when *index* is out of range.

        >>> tl = TempoList()
        >>> for t in (100.0, 120.0, 140.0): tl.append(t)
        >>> tl.next()   # activate 100.0 at index 0
        100.0
        >>> tl.remove(2)          # remove inactive 140.0
        >>> tl.index              # pointer unchanged
        0
        >>> tl.remove(0)          # remove the active 100.0
        >>> tl.current            # moved to next: 120.0
        120.0
        """
        if not 0 <= index < len(self._tempos):
            raise IndexError(
                f"TempoList index {index} out of range for list of length "
                f"{len(self._tempos)}"
            )
        was_active = (index == self._index)
        del self._tempos[index]

        if not self._tempos:
            self._index = -1
        elif was_active:
            # Wrap to 0 if we just removed the last entry
            if self._index >= len(self._tempos):
                self._index = 0
            # else: self._index already points at what was index+1
        elif index < self._index:
            self._index -= 1
        # else index > self._index: pointer unaffected

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
