"""
constants.py – visual and layout constants for big-tempo.

Keeping these separate means the rest of the modules (config, midi, cli)
are importable on a headless machine without pulling in tkinter.
"""

# ── Window geometry ────────────────────────────────────────────────────────────
WINDOW_SCALE      = 1.3
DEFAULT_WIDTH_IN  = WINDOW_SCALE * 5.2   # wider than original to fit button column
DEFAULT_HEIGHT_IN = WINDOW_SCALE * 1.5
DEFAULT_UPDATE_MS = 100

# ── Text / colour ──────────────────────────────────────────────────────────────
FONT_FAMILY       = "Helvetica"
DEFAULT_BG        = "white"
DEFAULT_FG        = "black"
DEFAULT_PRECISION = 1

# ── JACK transport indicator ───────────────────────────────────────────────────
IND_SIZE      = 30     # square side length (px)
IND_GAP       = 15     # gap between indicator and tempo text (px)
COLOR_ROLLING = "#C00000"
COLOR_IDLE    = "gray"

# ── Undecorated‑window border ─────────────────────────────────────────────────
BORDER_COLOR = "black"
BORDER_PX    = 4

# ── Up / Down button column ────────────────────────────────────────────────────
BTN_COL_W     = 58    # pixel width of the button column
BTN_FONT_SIZE = 22    # ▲ / ▼ label size (pt)
SEP_COLOR     = "#cccccc"

# ── Race‑condition cooldown ────────────────────────────────────────────────────
# Seconds after a user‑initiated BPM change during which JACK tempo updates
# are silently ignored.  Prevents Hydrogen's delayed MIDI echo from
# overwriting what the user just set.
BPM_ADOPT_COOLDOWN = 1.5
