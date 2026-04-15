"""
app.py – BigTempo: the main tkinter application.

Responsibilities
----------------
* JACK transport polling (rolling flag + BPM)
* Rendering: big BPM text, rolling indicator, ▲/▼ buttons
* BPM state machine: user changes (buttons / incoming MIDI) vs. JACK changes
* Delegating MIDI I/O to MidiHandler
"""

import sys
import time
import tkinter as tk
import tkinter.font as tkfont

from big_tempo.config import clamp_bpm
from big_tempo.tempo_list import TempoList
from big_tempo.constants import (
    BPM_ADOPT_COOLDOWN,
    BORDER_COLOR,
    BORDER_PX,
    BTN_COL_W,
    BTN_FONT_SIZE,
    COLOR_IDLE,
    COLOR_ROLLING,
    FONT_FAMILY,
    IND_GAP,
    IND_SIZE,
    SEP_COLOR,
)
from big_tempo.midi import MidiHandler

try:
    import jack
    HAS_JACK = True
except ImportError:
    HAS_JACK = False


class BigTempo:
    """
    Main application.

    Parameters
    ----------
    root : tk.Tk
        The tkinter root window.
    args : argparse.Namespace
        Parsed CLI arguments (see ``cli.parse_args()``).
    cfg  : dict
        Loaded application config (see ``config.load_config()``).
    """

    def __init__(self, root: tk.Tk, args, cfg: dict):
        self.root        = root
        self.args        = args
        self.cfg         = cfg
        self.jack_client = None
        self.update_ms   = args.update_ms

        # ── BPM state ─────────────────────────────────────────────────────────
        self.current_bpm     = 120.0
        self._jack_bpm       = None    # last BPM seen from JACK; None = never seen
        self._rolling        = False
        self._last_user_time = 0.0     # monotonic timestamp of last user change

        # Button hold‑repeat job handle
        self._repeat_job = None

        # ── Tempo list (save / cycle / clear) ───────────────────────────────────────────
        self._tempo_list = TempoList()

        # ── JACK client ────────────────────────────────────────────────────────
        if HAS_JACK:
            try:
                self.jack_client = jack.Client("BigTempo")
            except jack.JackError as exc:
                print(f"JACK connect failed: {exc}", file=sys.stderr)

        # ── MIDI ───────────────────────────────────────────────────────────────
        self.midi = MidiHandler(cfg, root, self._on_midi_receive)

        self._drag_data: dict = {}
        self._setup_window()
        self._create_widgets()
        self.midi.start()
        self._update_loop()

    # ── BPM management ─────────────────────────────────────────────────────────
    def _clamp(self, bpm: float) -> float:
        return clamp_bpm(bpm, self.cfg)

    def _user_set_bpm(self, bpm: float) -> None:
        """Apply a user‑initiated BPM change and fire outgoing MIDI CC."""
        self.current_bpm     = self._clamp(bpm)
        self._last_user_time = time.monotonic()
        self.midi.send_bpm(self.current_bpm)

    # ── MIDI receive (runs on tkinter main thread) ─────────────────────────────
    def _on_midi_receive(self, action: str, amount: float, raw: int) -> None:
        if action == "up":
            self._user_set_bpm(self.current_bpm + amount)
        elif action == "down":
            self._user_set_bpm(self.current_bpm - amount)
        elif action == "set":
            from big_tempo.config import midi_value_to_bpm
            self._user_set_bpm(midi_value_to_bpm(raw, self.cfg))
        elif action == "list_append":
            self._tempo_list.append(self.current_bpm)
        elif action == "list_next":
            bpm = self._tempo_list.next()
            if bpm is not None:
                self._user_set_bpm(bpm)
        elif action == "list_clear":
            self._tempo_list.clear()

    # ── Button hold‑repeat ─────────────────────────────────────────────────────
    def _btn_press(self, direction: int) -> None:
        """Immediate tick on press, then schedule the first auto‑repeat."""
        inc   = float(self.cfg["buttons"].get("increment",       1.0))
        delay = int(  self.cfg["buttons"].get("repeat_delay_ms", 400))
        self._user_set_bpm(self.current_bpm + direction * inc)
        self._repeat_job = self.root.after(
            delay, lambda: self._btn_repeat(direction)
        )

    def _btn_repeat(self, direction: int) -> None:
        """Fire and reschedule at the faster repeat rate."""
        inc      = float(self.cfg["buttons"].get("increment",  1.0))
        interval = int(  self.cfg["buttons"].get("repeat_ms",  80))
        self._user_set_bpm(self.current_bpm + direction * inc)
        self._repeat_job = self.root.after(
            interval, lambda: self._btn_repeat(direction)
        )

    def _btn_release(self, _event=None) -> None:
        """Cancel any pending repeat job on button release."""
        if self._repeat_job is not None:
            self.root.after_cancel(self._repeat_job)
            self._repeat_job = None

    # ── Window setup ───────────────────────────────────────────────────────────
    def _setup_window(self) -> None:
        self.root.title("Big Tempo")
        self.root.configure(
            bg=BORDER_COLOR if self.args.no_titlebar else self.args.bg
        )
        try:
            ppi = self.root.winfo_fpixels("1i")
        except Exception:
            ppi = 96.0
        w = int(self.args.width_in  * ppi)
        h = int(self.args.height_in * ppi)
        self.root.geometry(f"{w}x{h}")
        if self.args.no_titlebar:
            self.root.overrideredirect(True)
        if self.args.always_on_top:
            self.root.attributes("-topmost", True)
        self.root.bind("<Escape>", lambda _: self.root.destroy())

    # ── Widgets ────────────────────────────────────────────────────────────────
    def _create_widgets(self) -> None:
        """
        Layout (schematic)
        ------------------
        outer ┌─────────────────────────────┬─┬──────────┐
              │  canvas                     │ │ btn_col  │
              │  [ ● ]  120.0               │ │   ▲      │
              │                             │ │   ▼      │
              └─────────────────────────────┴─┴──────────┘
                                             sep
        """
        pad = BORDER_PX if self.args.no_titlebar else 0
        bg  = self.args.bg
        fg  = self.args.fg

        outer = tk.Frame(
            self.root, bg=self.root.cget("bg"), bd=0, highlightthickness=0
        )
        outer.pack(fill="both", expand=True, padx=pad, pady=pad)

        # ── Button column ─────────────────────────────────────────────────────
        btn_frame = tk.Frame(
            outer, bg=bg, width=BTN_COL_W, bd=0, highlightthickness=0
        )
        btn_frame.pack(side="right", fill="y")
        btn_frame.pack_propagate(False)

        _kw = dict(
            font=(FONT_FAMILY, BTN_FONT_SIZE, "bold"),
            bg="#ececec",
            fg=fg,
            activebackground="#d0d0d0",
            activeforeground=fg,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=SEP_COLOR,
            cursor="hand2",
        )
        self.btn_up   = tk.Button(btn_frame, text="▲", **_kw)
        self.btn_down = tk.Button(btn_frame, text="▼", **_kw)
        self.btn_up.pack(  side="top",    expand=True, fill="both", padx=4, pady=(4, 2))
        self.btn_down.pack(side="bottom", expand=True, fill="both", padx=4, pady=(2, 4))

        for btn, direction in ((self.btn_up, +1), (self.btn_down, -1)):
            btn.bind("<ButtonPress-1>",   lambda e, d=direction: self._btn_press(d))
            btn.bind("<ButtonRelease-1>", self._btn_release)

        # Thin separator between canvas and button column
        sep = tk.Frame(outer, bg=SEP_COLOR, width=1, bd=0, highlightthickness=0)
        sep.pack(side="right", fill="y")

        # ── Canvas (indicator + big text) ─────────────────────────────────────
        self.canvas = tk.Canvas(outer, bg=bg, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.box = self.canvas.create_rectangle(
            0, 0, IND_SIZE, IND_SIZE,
            fill=COLOR_IDLE, outline=COLOR_IDLE,
        )
        self.text = self.canvas.create_text(
            0, 0, text="120.0", fill=fg, anchor="w",
            font=(FONT_FAMILY, 20),
        )

        # Drag + context menu (undecorated window only)
        if self.args.no_titlebar:
            self.canvas.bind("<Button-1>",   self._start_drag)
            self.canvas.bind("<B1-Motion>",  self._do_drag)
            self.root.bind_all("<Button-3>", self._show_context_menu)
            self.context_menu = tk.Menu(self.root, tearoff=0)
            self.context_menu.add_command(label="Quit",   command=self.root.destroy)
            self.context_menu.add_separator()
            self.context_menu.add_command(label="Cancel", command=lambda: None)

    # ── Drag support (no‑titlebar mode) ───────────────────────────────────────
    def _start_drag(self, event) -> None:
        self._drag_data = {
            "x":  event.x_root,       "y":  event.y_root,
            "wx": self.root.winfo_x(), "wy": self.root.winfo_y(),
        }

    def _do_drag(self, event) -> None:
        x = self._drag_data["wx"] + (event.x_root - self._drag_data["x"])
        y = self._drag_data["wy"] + (event.y_root - self._drag_data["y"])
        self.root.geometry(f"+{x}+{y}")

    def _show_context_menu(self, event) -> None:
        if not self.args.no_titlebar:
            return
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    # ── Font auto‑fit ──────────────────────────────────────────────────────────
    def _fit_font(self, avail_w: int, avail_h: int, sample: str) -> int:
        """Binary‑search for the largest font size that fits the given bounds."""
        if self.args.font_size:
            return self.args.font_size
        low, high, best = 10, 800, 20
        f = tkfont.Font(family=FONT_FAMILY, size=20)
        while low <= high:
            mid = (low + high) // 2
            f.config(size=mid)
            if (
                f.measure(sample)   < avail_w * 0.95
                and f.metrics("ascent") < avail_h * 0.95
            ):
                best, low = mid, mid + 1
            else:
                high = mid - 1
        return best

    # ── Main update loop ───────────────────────────────────────────────────────
    def _update_loop(self) -> None:
        # 1. Poll JACK ─────────────────────────────────────────────────────────
        if self.jack_client:
            try:
                state, pos = self.jack_client.transport_query()
                self._rolling = (state == jack.ROLLING)

                jack_bpm = (
                    pos.get("beats_per_minute")
                    if isinstance(pos, dict)
                    else getattr(pos, "beats_per_minute", None)
                )

                if jack_bpm and jack_bpm > 0:
                    jack_changed = (
                        self._jack_bpm is None
                        or abs(jack_bpm - self._jack_bpm) > 0.05
                    )
                    if jack_changed:
                        self._jack_bpm = jack_bpm
                        # Only adopt if the user hasn't just changed something
                        if (time.monotonic() - self._last_user_time
                                > BPM_ADOPT_COOLDOWN):
                            self.current_bpm = self._clamp(jack_bpm)

            except Exception as exc:
                print(f"JACK query error: {exc}", file=sys.stderr)

        # 2. Render ────────────────────────────────────────────────────────────
        display = f"{self.current_bpm:.{self.args.precision}f}"
        self.canvas.itemconfig(self.text, text=display)
        clr = COLOR_ROLLING if self._rolling else COLOR_IDLE
        self.canvas.itemconfig(self.box, fill=clr, outline=clr)

        self.root.update_idletasks()
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()

        f_size = self._fit_font(cw - IND_SIZE - IND_GAP, ch, "000.0")
        self.canvas.itemconfig(self.text, font=(FONT_FAMILY, f_size))

        f       = tkfont.Font(family=FONT_FAMILY, size=f_size)
        text_w  = f.measure(display)
        total_w = IND_SIZE + IND_GAP + text_w
        sx      = (cw - total_w) // 2
        my      = ch // 2
        y_off   = f.metrics("descent") // 2

        self.canvas.coords(
            self.box,
            sx, my - IND_SIZE // 2,
            sx + IND_SIZE, my + IND_SIZE // 2,
        )
        self.canvas.coords(
            self.text,
            sx + IND_SIZE + IND_GAP, my + y_off,
        )

        self.root.after(self.update_ms, self._update_loop)
