"""
tests/test_tempo_list.py – unit tests for TempoList.

No display, JACK, or mididings required.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from big_tempo.tempo_list import TempoList


# ── Initial state ──────────────────────────────────────────────────────────────

class TestInitialState:
    def test_empty_on_construction(self):
        assert len(TempoList()) == 0

    def test_index_is_minus_one_initially(self):
        assert TempoList().index == -1

    def test_current_is_none_initially(self):
        assert TempoList().current is None

    def test_tempos_is_empty_list(self):
        assert TempoList().tempos == []

    def test_next_returns_none_when_empty(self):
        assert TempoList().next() is None


# ── append() ──────────────────────────────────────────────────────────────────

class TestAppend:
    def test_single_append_increases_length(self):
        tl = TempoList()
        tl.append(120.0)
        assert len(tl) == 1

    def test_multiple_appends(self):
        tl = TempoList()
        for bpm in (80.0, 100.0, 140.0):
            tl.append(bpm)
        assert len(tl) == 3

    def test_append_stores_correct_value(self):
        tl = TempoList()
        tl.append(137.5)
        assert tl.tempos == [137.5]

    def test_append_converts_to_float(self):
        tl = TempoList()
        tl.append(120)       # int
        assert isinstance(tl.tempos[0], float)

    def test_append_does_not_move_index(self):
        tl = TempoList()
        tl.append(120.0)
        assert tl.index == -1   # pointer has not advanced yet

    def test_append_after_next_does_not_reset_index(self):
        tl = TempoList()
        tl.append(100.0)
        tl.next()           # index → 0
        tl.append(200.0)    # should not disturb the pointer
        assert tl.index == 0

    def test_tempos_returns_copy(self):
        """Mutating the returned list must not affect internal state."""
        tl = TempoList()
        tl.append(120.0)
        copy = tl.tempos
        copy.append(999.0)
        assert len(tl) == 1


# ── next() ─────────────────────────────────────────────────────────────────────

class TestNext:
    def test_first_next_returns_first_tempo(self):
        tl = TempoList()
        tl.append(120.0)
        assert tl.next() == 120.0

    def test_next_advances_through_list(self):
        tl = TempoList()
        for bpm in (80.0, 100.0, 140.0):
            tl.append(bpm)
        assert tl.next() == 80.0
        assert tl.next() == 100.0
        assert tl.next() == 140.0

    def test_next_wraps_cyclically(self):
        tl = TempoList()
        tl.append(80.0)
        tl.append(160.0)
        tl.next()   # → 80.0  (index 0)
        tl.next()   # → 160.0 (index 1)
        result = tl.next()  # should wrap back to index 0
        assert result == 80.0
        assert tl.index == 0

    def test_next_single_element_always_returns_same(self):
        tl = TempoList()
        tl.append(120.0)
        for _ in range(5):
            assert tl.next() == 120.0

    def test_next_returns_none_on_empty(self):
        assert TempoList().next() is None

    def test_next_index_matches_returned_value(self):
        tl = TempoList()
        tl.append(70.0)
        tl.append(90.0)
        tl.append(110.0)
        for _ in range(6):   # two full cycles
            bpm = tl.next()
            assert bpm == tl.tempos[tl.index]

    def test_next_updates_current(self):
        tl = TempoList()
        tl.append(90.0)
        tl.append(110.0)
        tl.next()
        assert tl.current == 90.0
        tl.next()
        assert tl.current == 110.0

    def test_full_cycle_returns_to_start(self):
        tempos = [60.0, 90.0, 120.0, 160.0, 200.0]
        tl = TempoList()
        for t in tempos:
            tl.append(t)
        # Walk two complete cycles and verify every value
        for cycle in range(2):
            for expected in tempos:
                assert tl.next() == expected, f"cycle {cycle}, expected {expected}"


# ── clear() ────────────────────────────────────────────────────────────────────

class TestClear:
    def test_clear_empties_list(self):
        tl = TempoList()
        tl.append(120.0)
        tl.clear()
        assert len(tl) == 0

    def test_clear_resets_index(self):
        tl = TempoList()
        tl.append(120.0)
        tl.next()
        tl.clear()
        assert tl.index == -1

    def test_clear_resets_current(self):
        tl = TempoList()
        tl.append(120.0)
        tl.next()
        tl.clear()
        assert tl.current is None

    def test_next_after_clear_returns_none(self):
        tl = TempoList()
        tl.append(120.0)
        tl.clear()
        assert tl.next() is None

    def test_append_after_clear_works_normally(self):
        tl = TempoList()
        tl.append(120.0)
        tl.next()
        tl.clear()
        tl.append(90.0)
        assert tl.next() == 90.0
        assert tl.index == 0

    def test_clear_on_empty_list_is_safe(self):
        tl = TempoList()
        tl.clear()   # must not raise
        assert len(tl) == 0

    def test_multiple_clears_are_idempotent(self):
        tl = TempoList()
        tl.append(100.0)
        tl.clear()
        tl.clear()
        assert len(tl) == 0
        assert tl.index == -1


# ── current property ───────────────────────────────────────────────────────────

class TestCurrent:
    def test_none_before_first_next(self):
        tl = TempoList()
        tl.append(100.0)
        assert tl.current is None   # list has items but pointer not advanced yet

    def test_reflects_last_next_result(self):
        tl = TempoList()
        tl.append(100.0)
        tl.append(200.0)
        tl.next()
        assert tl.current == 100.0


# ── Iteration ──────────────────────────────────────────────────────────────────

class TestIteration:
    def test_iter_yields_all_tempos_in_order(self):
        tl = TempoList()
        expected = [80.0, 100.0, 120.0, 160.0]
        for t in expected:
            tl.append(t)
        assert list(tl) == expected

    def test_iter_on_empty_yields_nothing(self):
        assert list(TempoList()) == []


# ── Interaction scenarios ──────────────────────────────────────────────────────

class TestScenarios:
    def test_live_performance_workflow(self):
        """Simulate a real gig: save tempos during soundcheck, cycle live."""
        tl = TempoList()

        # Soundcheck: save the set's tempos in order
        set_tempos = [92.0, 110.0, 128.0, 75.0]
        for t in set_tempos:
            tl.append(t)

        # Performance: step through cyclically
        for t in set_tempos:
            assert tl.next() == t

        # Second run-through (encore)
        for t in set_tempos:
            assert tl.next() == t

        # End of night: clear for next show
        tl.clear()
        assert len(tl) == 0
        assert tl.next() is None

    def test_append_during_cycle(self):
        """Appending while mid-cycle should extend the list without jumping."""
        tl = TempoList()
        tl.append(100.0)
        tl.append(120.0)
        tl.next()           # index 0 → 100.0
        tl.append(140.0)    # add at end; index still 0
        tl.next()           # index 1 → 120.0
        tl.next()           # index 2 → 140.0 (new entry reached)
        tl.next()           # wraps to index 0 → 100.0
        assert tl.current == 100.0


# ── goto() ─────────────────────────────────────────────────────────────────────

class TestGoto:
    def test_returns_correct_bpm(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        assert tl.goto(1) == 120.0

    def test_sets_index(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.goto(2)
        assert tl.index == 2

    def test_goto_first(self):
        tl = TempoList()
        for t in (100.0, 120.0): tl.append(t)
        tl.goto(1)
        tl.goto(0)
        assert tl.index == 0
        assert tl.current == 100.0

    def test_goto_last(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.goto(2)
        assert tl.current == 140.0

    def test_updates_current(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.goto(1)
        assert tl.current == 120.0

    def test_next_continues_from_goto_position(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.goto(1)           # jump to 120.0 (index 1)
        assert tl.next() == 140.0   # advances to index 2

    def test_goto_then_next_wraps(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.goto(2)           # jump to last
        assert tl.next() == 100.0   # wraps to index 0

    def test_out_of_range_raises(self):
        tl = TempoList()
        tl.append(120.0)
        with pytest.raises(IndexError):
            tl.goto(1)

    def test_negative_index_raises(self):
        tl = TempoList()
        tl.append(120.0)
        with pytest.raises(IndexError):
            tl.goto(-1)

    def test_empty_list_raises(self):
        with pytest.raises(IndexError):
            TempoList().goto(0)


# ── remove() ───────────────────────────────────────────────────────────────────

class TestRemove:

    # ── basic correctness ──────────────────────────────────────────────────────

    def test_reduces_length(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.remove(1)
        assert len(tl) == 2

    def test_removes_correct_entry(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.remove(1)
        assert tl.tempos == [100.0, 140.0]

    def test_out_of_range_raises(self):
        tl = TempoList()
        tl.append(120.0)
        with pytest.raises(IndexError):
            tl.remove(1)

    def test_negative_index_raises(self):
        tl = TempoList()
        tl.append(120.0)
        with pytest.raises(IndexError):
            tl.remove(-1)

    def test_empty_list_raises(self):
        with pytest.raises(IndexError):
            TempoList().remove(0)

    # ── pointer rules: list becomes empty ─────────────────────────────────────

    def test_remove_only_entry_resets_index(self):
        tl = TempoList()
        tl.append(120.0)
        tl.remove(0)
        assert tl.index == -1

    def test_remove_only_entry_current_is_none(self):
        tl = TempoList()
        tl.append(120.0)
        tl.remove(0)
        assert tl.current is None

    # ── pointer rules: removing the active entry ───────────────────────────────

    def test_remove_active_middle_goes_to_next(self):
        """Remove entry 1 (active) from [100, 120, 140] → new active = 140 at idx 1."""
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.goto(1)           # activate 120.0
        tl.remove(1)
        assert tl.current == 140.0
        assert tl.index   == 1

    def test_remove_active_last_wraps_to_first(self):
        """Remove last active entry → pointer wraps to index 0."""
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.goto(2)           # activate 140.0 (last)
        tl.remove(2)
        assert tl.current == 100.0
        assert tl.index   == 0

    def test_remove_active_first_goes_to_new_first(self):
        """Remove first active entry → pointer stays at 0, now pointing to old second."""
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.goto(0)           # activate 100.0
        tl.remove(0)
        assert tl.current == 120.0
        assert tl.index   == 0

    def test_remove_active_two_entry_list(self):
        tl = TempoList()
        tl.append(100.0); tl.append(120.0)
        tl.goto(0)           # activate 100.0
        tl.remove(0)
        assert tl.current == 120.0
        assert tl.index   == 0

    # ── pointer rules: removing an inactive entry ──────────────────────────────

    def test_remove_before_active_shifts_pointer(self):
        """Remove entry before the active one → same entry stays active."""
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.goto(2)           # activate 140.0 at index 2
        tl.remove(0)         # remove 100.0 (before active)
        assert tl.current == 140.0
        assert tl.index   == 1   # shifted from 2 → 1

    def test_remove_after_active_pointer_unchanged(self):
        """Remove entry after the active one → pointer unchanged."""
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.goto(0)           # activate 100.0 at index 0
        tl.remove(2)         # remove 140.0 (after active)
        assert tl.current == 100.0
        assert tl.index   == 0

    def test_remove_inactive_before_no_active_pointer_unchanged(self):
        """Pointer is -1 (no active entry); remove doesn't crash."""
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        # pointer is -1 (never advanced)
        tl.remove(1)
        assert tl.index == -1

    # ── next() still works after remove ───────────────────────────────────────

    def test_next_works_after_removing_active(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.goto(1)
        tl.remove(1)         # removes 120.0; now active is 140.0 at idx 1
        assert tl.next() == 100.0   # wraps: idx 2 would be out of range → 0

    def test_next_works_after_removing_inactive(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.goto(0)
        tl.remove(2)         # removes 140.0; active still 100.0 at idx 0
        assert tl.next() == 120.0   # advances to index 1


# ── set_at() ───────────────────────────────────────────────────────────────────

class TestSetAt:
    def test_updates_value(self):
        tl = TempoList()
        tl.append(100.0); tl.append(120.0)
        tl.set_at(1, 125.0)
        assert tl.tempos[1] == 125.0

    def test_converts_to_float(self):
        tl = TempoList()
        tl.append(120)
        tl.set_at(0, 130)
        assert isinstance(tl.tempos[0], float)

    def test_does_not_move_pointer_when_inactive(self):
        tl = TempoList()
        tl.append(100.0); tl.append(120.0)
        tl.set_at(1, 125.0)
        assert tl.index == -1

    def test_does_not_move_pointer_when_active(self):
        tl = TempoList()
        tl.append(100.0); tl.append(120.0)
        tl.goto(0)
        tl.set_at(0, 105.0)
        assert tl.index == 0

    def test_active_entry_value_updates(self):
        """set_at on the active entry changes what current returns."""
        tl = TempoList()
        tl.append(100.0); tl.append(120.0)
        tl.goto(0)
        tl.set_at(0, 105.0)
        assert tl.current == 105.0

    def test_other_entries_unaffected(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.set_at(1, 125.0)
        assert tl.tempos[0] == 100.0
        assert tl.tempos[2] == 140.0

    def test_out_of_range_raises(self):
        tl = TempoList()
        tl.append(120.0)
        with pytest.raises(IndexError):
            tl.set_at(1, 130.0)

    def test_negative_index_raises(self):
        tl = TempoList()
        tl.append(120.0)
        with pytest.raises(IndexError):
            tl.set_at(-1, 130.0)

    def test_empty_list_raises(self):
        with pytest.raises(IndexError):
            TempoList().set_at(0, 120.0)

    def test_next_returns_updated_value(self):
        """After set_at, next() yields the new value."""
        tl = TempoList()
        tl.append(100.0); tl.append(120.0)
        tl.set_at(0, 105.0)
        assert tl.next() == 105.0


# ── prev() ─────────────────────────────────────────────────────────────────────

class TestPrev:
    def test_empty_returns_none(self):
        assert TempoList().prev() is None

    def test_pointer_unchanged_on_empty(self):
        tl = TempoList()
        tl.prev()
        assert tl.index == -1

    def test_from_inactive_goes_to_last(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        assert tl.prev() == 140.0
        assert tl.index  == 2

    def test_from_first_wraps_to_last(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.goto(0)
        assert tl.prev() == 140.0
        assert tl.index  == 2

    def test_decrements_normally(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.goto(2)
        assert tl.prev() == 120.0
        assert tl.index  == 1

    def test_single_entry_stays_put(self):
        tl = TempoList()
        tl.append(120.0)
        assert tl.prev() == 120.0
        assert tl.prev() == 120.0   # wraps back to itself

    def test_prev_then_next_returns_to_start(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.goto(1)
        tl.prev()   # → 0
        tl.next()   # → 1
        assert tl.current == 120.0

    def test_full_backward_cycle(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        results = [tl.prev() for _ in range(4)]
        assert results == [140.0, 120.0, 100.0, 140.0]

    def test_interleaved_next_and_prev(self):
        tl = TempoList()
        for t in (100.0, 120.0, 140.0): tl.append(t)
        tl.next()   # 100
        tl.next()   # 120
        tl.prev()   # 100
        assert tl.current == 100.0
        assert tl.index   == 0
