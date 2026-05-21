"""
cli.py – command-line argument parsing for big-tempo.
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
    Parse command-line arguments.

    Parameters
    ----------
    argv : list[str] | None
        Argument list to parse.  ``None`` means use ``sys.argv[1:]``.
    """
    p = argparse.ArgumentParser(
        prog="big-tempo",
        description=(
            "Big JACK tempo display with MIDI/OSC control.\n"
            "Config file: ~/.config/big-tempo/config.py  (Python dict literal)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help=(
            "Path to a Python dict-literal config file. "
            "Default: ~/.config/big-tempo/config.py. "
            "The file is parsed with ast.literal_eval (no arbitrary code executed). "
            "Run with --config /dev/null to ignore any saved config."
        ),
    )
    p.add_argument(
        "--width-in",
        type=float,
        default=DEFAULT_WIDTH_IN,
        metavar="INCHES",
        help=(
            f"Initial window width in inches (default: {DEFAULT_WIDTH_IN:.2f}). "
            "The window is resizable; this only sets the starting size."
        ),
    )
    p.add_argument(
        "--height-in",
        type=float,
        default=DEFAULT_HEIGHT_IN,
        metavar="INCHES",
        help=(
            f"Initial window height in inches (default: {DEFAULT_HEIGHT_IN:.2f}). "
            "The window grows automatically when the tempo list panel appears."
        ),
    )
    p.add_argument(
        "--update-ms",
        type=int,
        default=DEFAULT_UPDATE_MS,
        metavar="MS",
        help=(
            f"How often (in milliseconds) to poll the JACK transport and "
            f"refresh the display (default: {DEFAULT_UPDATE_MS}ms = "
            f"{1000//DEFAULT_UPDATE_MS} fps). "
            "This also sets the maximum latency for incoming MIDI CC events, "
            "since mididings callbacks are delivered to the main thread at "
            "the next update tick. "
            "Lower values (e.g. 20-50ms) reduce MIDI latency at negligible CPU cost. "
            "Values below ~16ms provide no additional benefit."
        ),
    )
    p.add_argument(
        "--font-size",
        type=int,
        default=None,
        metavar="PT",
        help=(
            "Fix the BPM display font at this size in points. "
            "By default the font scales automatically to fill the window."
        ),
    )
    p.add_argument(
        "--precision",
        type=int,
        default=DEFAULT_PRECISION,
        metavar="DIGITS",
        help=(
            f"Number of decimal places shown in the BPM readout "
            f"(default: {DEFAULT_PRECISION}). "
            "Use 0 for integer-only display when quantize=1.0."
        ),
    )
    p.add_argument(
        "--bg",
        default=DEFAULT_BG,
        metavar="COLOR",
        help=(
            f"Window background colour (default: {DEFAULT_BG!r}). "
            "Accepts any Tk colour name (e.g. 'black', '#1a1a1a')."
        ),
    )
    p.add_argument(
        "--fg",
        default=DEFAULT_FG,
        metavar="COLOR",
        help=(
            f"Foreground (text and indicator) colour (default: {DEFAULT_FG!r}). "
            "Accepts any Tk colour name."
        ),
    )
    p.add_argument(
        "--always-on-top",
        action="store_true",
        help=(
            "Keep the window above all other windows. "
            "Useful on stage when you want the tempo always visible."
        ),
    )
    p.add_argument(
        "--no-titlebar",
        action="store_true",
        help=(
            "Remove the window title bar and OS chrome. "
            "Enables click-drag anywhere on the canvas to reposition the window. "
            "Right-click shows a Quit/Cancel menu."
        ),
    )

    import os as _os
    _default_pos = _os.path.expanduser("~/.config/big-tempo/window.pos")
    p.add_argument(
        "--save-pos",
        nargs="?",
        const=_default_pos,   # value used when flag given with no argument
        default=None,          # value used when flag is absent entirely
        metavar="FILE",
        help=(
            "Save the window position on exit and restore it on the next run. "
            f"With no argument, uses {_default_pos}. "
            "Pass an explicit path to use a different file, e.g. when running "
            "multiple configs that need separate positions."
        ),
    )

    return p.parse_args(argv)
