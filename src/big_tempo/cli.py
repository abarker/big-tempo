"""
cli.py – command‑line argument parsing for big-tempo.
"""

import argparse

from big_tempo.constants import (
    DEFAULT_BG,
    DEFAULT_FG,
    DEFAULT_HEIGHT_IN,
    DEFAULT_PRECISION,
    DEFAULT_UPDATE_MS,
    DEFAULT_WIDTH_IN,
)


def parse_args(argv=None) -> argparse.Namespace:
    """
    Parse command‑line arguments.

    Parameters
    ----------
    argv : list[str] | None
        Argument list to parse.  ``None`` means use ``sys.argv[1:]``.
    """
    p = argparse.ArgumentParser(
        prog="big-tempo",
        description="Big JACK tempo display with MIDI control via mididings.",
    )
    p.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="JSON config file (default: ~/.config/big-tempo/config.json)",
    )
    p.add_argument("--width-in",  type=float, default=DEFAULT_WIDTH_IN)
    p.add_argument("--height-in", type=float, default=DEFAULT_HEIGHT_IN)
    p.add_argument("--update-ms", type=int,   default=DEFAULT_UPDATE_MS)
    p.add_argument(
        "--font-size",
        type=int,
        default=None,
        help="Fixed font size in points (overrides auto‑fit)",
    )
    p.add_argument("--precision", type=int,   default=DEFAULT_PRECISION)
    p.add_argument("--bg",        default=DEFAULT_BG)
    p.add_argument("--fg",        default=DEFAULT_FG)
    p.add_argument("--always-on-top", action="store_true")
    p.add_argument(
        "--no-titlebar",
        action="store_true",
        help="Open without a title bar (enables click‑drag to move)",
    )
    return p.parse_args(argv)
