"""
big_tempo – JACK tempo display with MIDI control.

Headless-safe public API
------------------------
Only modules that do **not** import tkinter, jack, or mididings are
re-exported here.  This keeps ``import big_tempo`` safe on headless
machines and in test environments.

``BigTempo`` (the tkinter application) is available as:

    from big_tempo.app import BigTempo

It is intentionally not imported at the package level to avoid pulling in
tkinter when only the config helpers or CLI parser are needed.
"""

__version__ = "0.2.0"

# These modules are unconditionally safe – no display, JACK, or MIDI required.
from big_tempo.config import (   # noqa: F401
    DEFAULT_CFG,
    clamp_bpm,
    bpm_to_midi_value,
    midi_value_to_bpm,
    load_config,
)
from big_tempo.cli import parse_args  # noqa: F401

__all__ = [
    "__version__",
    "DEFAULT_CFG",
    "load_config",
    "parse_args",
    "clamp_bpm",
    "bpm_to_midi_value",
    "midi_value_to_bpm",
]
