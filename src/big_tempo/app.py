"""
app.py – BigTempo: the main tkinter application.

Responsibilities
----------------
* JACK transport polling (rolling flag + BPM)
* Rendering: big BPM text, rolling indicator, ▲/▼ buttons
* BPM state machine: user changes (buttons / incoming MIDI) vs. JACK changes
* Delegating MIDI I/O to MidiHandler
"""

import os
import sys
import time
import tkinter as tk
import tkinter.font as tkfont

from big_tempo.config import clamp_bpm, initial_tempos, load_config, quantize_bpm
from big_tempo.tempo_list import TempoList
from big_tempo.constants import (
    BPM_ADOPT_COOLDOWN,
    LIST_PANEL_H,
    LIST_PILL_ACT_BG,
    LIST_PILL_ACT_FG,
    LIST_PILL_BG,
    LIST_PILL_FG,
    LIST_PILL_FONT_SIZE,
    LIST_PILL_GAP,
    LIST_PILL_PAD_X,
    LIST_PILL_PAD_Y,
    LIST_SEP_COLOR,
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
from big_tempo.osc  import OscSender

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
        self._prev_rolling   = None    # None = first poll; no edge fired yet
        self._last_user_time = 0.0     # monotonic timestamp of last user change

        # ── Render-change tracking (skip canvas work when nothing changed) ──────
        self._last_display:      str            = ""
        self._last_clr:          str            = ""
        self._last_canvas_size:  tuple[int,int] = (0, 0)

        # Button hold‑repeat job handle
        self._repeat_job = None

        # ── Tempo list (save / cycle / clear) ───────────────────────────────────────────
        self._tempo_list = TempoList()
        # Preloaded from the config; no entry is active until list_next / list_prev,
        # just as after list_append, so the display keeps following JACK until then.
        for bpm in initial_tempos(cfg):
            self._tempo_list.append(bpm)

        # ── JACK client ────────────────────────────────────────────────────────
        if HAS_JACK:
            try:
                self.jack_client = jack.Client("BigTempo")
            except jack.JackError as exc:
                print(f"JACK connect failed: {exc}", file=sys.stderr)

        # ── MIDI ───────────────────────────────────────────────────────────────
        self.midi = MidiHandler(cfg, root, self._on_midi_receive)

        # ── OSC ───────────────────────────────────────────────────────
        self.osc  = OscSender(cfg)

        # ── Config hot-reload ──────────────────────────────────────────────
        from big_tempo.config import DEFAULT_CONFIG_PATH
        self._cfg_path = args.config if args.config is not None else DEFAULT_CONFIG_PATH
        self._cfg_mtime: float = self._get_cfg_mtime()

        if cfg.get("debug", False):
            print(f"[app] debug mode ON", file=sys.stderr, flush=True)
            print(f"[app] OSC sender enabled={self.osc.enabled}", file=sys.stderr, flush=True)
            print(f"[app] JACK client={'connected' if self.jack_client else 'not connected'}",
                  file=sys.stderr, flush=True)
            print(f"[app] watching config: {self._cfg_path}", file=sys.stderr, flush=True)

        self._drag_data: dict = {}
        self._setup_window()
        self._create_widgets()
        if self._tempo_list.tempos:
            self._dbg(f"tempo_list preloaded: {self._tempo_list.tempos}")
            self._refresh_list_panel()
        self.midi.start()
        self._update_loop()

    # ── BPM management ─────────────────────────────────────────────────────────
    def _dbg(self, msg: str) -> None:
        """Print *msg* to stderr when debug mode is enabled."""
        if self.cfg.get("debug", False):
            print(f"[app] {msg}", file=sys.stderr, flush=True)

    def _get_cfg_mtime(self) -> float:
        """Return the config file's mtime, or 0.0 if the file doesn't exist."""
        try:
            return os.stat(self._cfg_path).st_mtime
        except OSError:
            return 0.0

    def _check_config_reload(self) -> None:
        """
        Compare the config file's current mtime against the stored value.
        If it has changed, reload and apply the new config.

        Called on every update-loop tick.  os.stat() is a single syscall
        (~microseconds) so the overhead is negligible.

        What changes live
        -----------------
        - All receive / send mappings
        - min_bpm, max_bpm, quantize, quantize_jack
        - buttons (increment, repeat timing)
        - debug flag
        - OSC targets (OscSender pool is rebuilt fresh on every reload)

        What requires a restart
        -----------------------
        - midi.client_name  (mididings JACK client cannot be renamed at runtime)
        - tempo_list  (read only at startup, so a reload never discards tempos
          appended or adjusted while playing)
        """
        mtime = self._get_cfg_mtime()
        if mtime == 0.0 or mtime == self._cfg_mtime:
            return
        self._cfg_mtime = mtime

        new_cfg = load_config(self._cfg_path)
        if new_cfg is None:
            return   # load_config already printed a warning

        # Capture values that need a before/after comparison *before* the swap
        old_midi_name = self.cfg.get("midi", {}).get("client_name")
        new_midi_name = new_cfg.get("midi", {}).get("client_name")

        # Swap the config dict in place on all objects that hold a reference
        self.cfg      = new_cfg
        self.midi.cfg = new_cfg
        # Fresh OscSender on every reload – pool is lazy so this is free
        self.osc      = OscSender(new_cfg)
        restart_notes = []
        if old_midi_name != new_midi_name:
            restart_notes.append(
                f"  midi.client_name: '{old_midi_name}' → '{new_midi_name}'"
                " (restart required)"
            )

        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] config reloaded: {self._cfg_path}", file=sys.stderr, flush=True)
        if restart_notes:
            for note in restart_notes:
                print(note, file=sys.stderr, flush=True)
        self._dbg(f"new cfg keys: {list(new_cfg.keys())}")

    def _clamp(self, bpm: float) -> float:
        return clamp_bpm(bpm, self.cfg)

    def _fire_send(
        self,
        trigger: str,
        bpm: float,
        raw: int = 0,
        rolling: int = 0,
    ) -> None:
        """
        Iterate the unified ``cfg["send"][trigger]`` list and dispatch each
        action to the appropriate handler.

        ``"send": "MIDI"`` → ``self.midi.send_with_context``
        ``"send": "OSC"``  → ``self.osc.send_with_context``
        """
        for spec in self.cfg.get("send", {}).get(trigger, []):
            send_type = spec.get("send", "")
            if send_type == "MIDI":
                self._dbg(f"  → MIDI CC{spec.get('cc')}  trigger={trigger}")
                self.midi.send_with_context(spec, bpm=bpm, raw=raw, rolling=rolling)
            elif send_type == "OSC":
                self._dbg(
                    f"  → OSC {spec.get('address')}"
                    f" → {spec.get('host')}:{spec.get('port')}"
                    f"  trigger={trigger}"
                )
                self.osc.send_with_context(spec, bpm=bpm, raw=raw, rolling=rolling)

    def _user_set_bpm(self, bpm: float) -> None:
        """Apply a user‑initiated BPM change and fire outgoing MIDI CC and OSC."""
        quantized            = quantize_bpm(bpm, self.cfg)
        self.current_bpm     = self._clamp(quantized)
        self._last_user_time = time.monotonic()
        self._dbg(
            f"_user_set_bpm: raw={bpm:.3f}  quantized={quantized:.3f}"
            f"  clamped={self.current_bpm:.3f}"
        )
        self._fire_send("on_change", bpm=self.current_bpm, raw=0)

        # Update the active tempo-list entry to match the new BPM
        if self.cfg.get("list_update_on_change", True):
            if self._tempo_list.replace_current(self.current_bpm):
                self._dbg(
                    f"list_update_on_change: slot {self._tempo_list.index} "
                    f"→ {self.current_bpm:.3f}"
                )
                if not self._fast_update_active_pill(self.current_bpm):
                    self._refresh_list_panel()

    # ── MIDI receive (runs on tkinter main thread) ─────────────────────────────
    def _on_midi_receive(
        self,
        action: str,
        amount: float,
        raw: int,
        send_specs: list | None = None,
    ) -> None:
        self._dbg(f"MIDI receive: action={action!r}  raw={raw}  amount={amount}")
        if action == "up":
            self._user_set_bpm(self.current_bpm + amount)
        elif action == "down":
            self._user_set_bpm(self.current_bpm - amount)
        elif action == "set":
            from big_tempo.config import midi_value_to_bpm
            self._user_set_bpm(midi_value_to_bpm(raw, self.cfg))
        elif action == "list_append":
            self._gui_list_append()
        elif action == "list_next":
            self._gui_list_next()
        elif action == "list_prev":
            self._gui_list_prev()
        elif action == "list_clear":
            self._tempo_list.clear()
            self._refresh_list_panel()
        elif action == "osc_only":
            pass   # no BPM change; sends fired below if present
        elif action == "midi_only":
            pass   # no BPM change; sends fired below if present
        # Fire per-receive sends (independent of action type)
        for spec in (send_specs or []):
            send_type = spec.get("send", "")
            if send_type == "OSC":
                self.osc.send_with_context(spec, bpm=self.current_bpm, raw=raw)
            elif send_type == "MIDI":
                self.midi.send_with_context(spec, bpm=self.current_bpm, raw=raw)

    # ── GUI tempo-list actions ─────────────────────────────────────────────────
    def _pill_canvas_scroll(self, event, direction: int) -> None:
        """
        Canvas-level scroll dispatcher for the pill row.

        ``<Button-4/5>`` and ``<MouseWheel>`` cannot be used with canvas item
        ``tag_bind`` (Tk rejects them with "requested illegal events").  Instead
        we bind at the canvas-widget level and use ``find_overlapping`` to
        determine whether the cursor is over a specific pill.

        - Over a pill   → nudge that pill's stored value (no BPM change)
        - Over empty space → global BPM scroll (same as the main canvas)
        """
        items = self._pill_canvas.find_overlapping(
            event.x, event.y, event.x, event.y
        )
        for item_id in reversed(items):   # topmost item first
            index = self._pill_item_to_index.get(item_id)
            if index is not None:
                self._gui_pill_scroll(index, direction)
                return
        # Cursor is over the background or separator line → global scroll
        self._scroll_bpm(direction)

    def _gui_pill_scroll(self, index: int, direction: int) -> None:
        """
        Nudge the stored BPM of pill *index* by one increment step.

        If the scrolled pill is the active one the playing tempo follows
        immediately (matching the reverse behavior where button/MIDI changes
        update the active slot).  Inactive pills are edited in-place without
        affecting the playing tempo.

        Quantize and clamp are applied identically to any other BPM change.
        """
        inc     = float(self.cfg.get("buttons", {}).get("increment", 1.0))
        raw     = self._tempo_list.tempos[index] + direction * inc
        new_bpm = self._clamp(quantize_bpm(raw, self.cfg))
        self._tempo_list.set_at(index, new_bpm)
        if index == self._tempo_list.index:
            # Active pill: update playing BPM and fire sends.
            # _user_set_bpm calls _refresh_list_panel internally.
            self._user_set_bpm(new_bpm)
        else:
            self._refresh_list_panel()

    def _scroll_bpm(self, direction: int) -> None:
        """Handle mouse-wheel scroll over the canvas or pill row."""
        inc = float(self.cfg.get("buttons", {}).get("increment", 1.0))
        self._user_set_bpm(self.current_bpm + direction * inc)

    def _gui_list_next(self) -> None:
        """Advance the tempo list by one step and apply the new BPM."""
        bpm = self._tempo_list.next()
        if bpm is not None:
            self._user_set_bpm(bpm)
        self._refresh_list_panel()

    def _gui_list_prev(self) -> None:
        """Step the tempo list back one entry and apply the new BPM."""
        bpm = self._tempo_list.prev()
        if bpm is not None:
            self._user_set_bpm(bpm)
        self._refresh_list_panel()

    def _gui_list_append(self) -> None:
        """
        Save the current BPM to the list (MIDI ``list_append`` or double-click).

        When ``activate_on_append`` is set in the config, the newly-added
        entry becomes the active tempo immediately, so subsequent user changes
        edit it in place (subject to ``list_update_on_change``) and ``list_next``
        advances from it.  The current playing BPM is unchanged either way –
        the appended value already equals ``current_bpm``.
        """
        activate = self.cfg.get("activate_on_append", False)
        index    = self._tempo_list.append(self.current_bpm, activate=activate)
        self._dbg(
            f"list_append: slot {index} = {self.current_bpm:.3f}"
            f"{'  (activated)' if activate else ''}"
        )
        self._refresh_list_panel()

    def _gui_pill_select(self, index: int) -> None:
        """Single-click on a pill: jump to that tempo."""
        bpm = self._tempo_list.goto(index)
        self._user_set_bpm(bpm)
        self._refresh_list_panel()

    def _gui_pill_remove(self, index: int) -> None:
        """
        Middle-click on a pill: remove that entry from the list.

        If the removed entry was active, the new active tempo (the next one
        in the list) is applied immediately.  If the list becomes empty the
        panel collapses but the current BPM is left unchanged.
        """
        was_active = (index == self._tempo_list.index)
        self._tempo_list.remove(index)
        if was_active and self._tempo_list.current is not None:
            self._user_set_bpm(self._tempo_list.current)
        self._refresh_list_panel()

    def _gui_pill_context(self, event, index: int) -> str:
        """
        Right-click on a pill: show a small context menu.

        Returns ``"break"`` so the event does not propagate to the
        no-titlebar ``bind_all`` quit menu.
        """
        bpm   = self._tempo_list.tempos[index]
        label = f"{bpm:.{self.args.precision}f}"
        menu  = tk.Menu(self.root, tearoff=0)
        menu.add_command(
            label=f"Switch to {label}",
            command=lambda: self._gui_pill_select(index),
        )
        menu.add_command(
            label="Remove from list",
            command=lambda: self._gui_pill_remove(index),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

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
    def _pos_path(self) -> str | None:
        """
        Return the resolved position-file path, or ``None`` if ``--save-pos``
        was not given.

        ``args.save_pos`` is ``None`` when the flag is absent and a path string
        (either the XDG default or an explicit one) when the flag is present.
        """
        return self.args.save_pos   # None → disabled; str → enabled

    def _save_pos(self) -> None:
        """
        Write the current window position to the position file.

        Does nothing when ``--save-pos`` was not supplied.  Errors are printed
        to stderr and suppressed so that a save failure never prevents the
        application from closing.
        """
        path = self._pos_path()
        if not path:
            return
        try:
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            dir_part = os.path.dirname(path)
            if dir_part:
                os.makedirs(dir_part, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"{x}\n{y}\n")
            self._dbg(f"saved window position ({x}, {y}) → {path}")
        except Exception as exc:
            print(f"Warning: could not save window position to {path!r}: {exc}",
                  file=sys.stderr)

    def _on_close(self) -> None:
        """
        Clean shutdown: save window position (if ``--save-pos`` is active),
        then destroy the root window.

        Bound to:
        - WM delete-window protocol (title-bar × button)
        - Context-menu Quit (no-titlebar mode)
        - SIGINT / SIGTERM (via ``__main__``)
        """
        self._save_pos()
        self.root.destroy()

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
        self._base_win_w = w
        self._base_win_h = h

        # Build geometry string: size always; position from saved file if present
        geo = f"{w}x{h}"
        pos_path = self._pos_path()
        if pos_path and os.path.exists(pos_path):
            try:
                parts = open(pos_path, encoding="utf-8").read().split()
                x, y  = int(parts[0]), int(parts[1])
                geo   = f"{w}x{h}+{x}+{y}"
                self._dbg(f"restored window position ({x}, {y}) from {pos_path}")
            except Exception as exc:
                print(f"Warning: could not read position file {pos_path!r}: {exc}",
                      file=sys.stderr)
        self.root.geometry(geo)

        if self.args.no_titlebar:
            self.root.overrideredirect(True)
        if self.args.always_on_top:
            self.root.attributes("-topmost", True)
        # Route all close paths through _on_close so position is always saved
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Tab / Shift+Tab navigate the tempo list
        self.root.bind("<Tab>",       lambda _: self._gui_list_next() or "break")
        self.root.bind("<Shift-Tab>", lambda _: self._gui_list_prev() or "break")

    # ── Widgets ────────────────────────────────────────────────────────────────
    def _create_widgets(self) -> None:
        """
        Layout (schematic)
        ------------------
        outer (vertical stacker)
          top_frame ┌──────────────────────────┬─┬──────────┐
                    │  canvas                  │ │ btn_col  │
                    │  [ ● ]  120.0            │ │   ▲      │
                    │                          │ │   ▼      │
                    └──────────────────────────┴─┴──────────┘
          list_sep  ────────────────────────────────────────  (1 px, hidden when empty)
          list_panel  92.0   110.0  [ 120.0 ]  75.0          (hidden when empty)
        """
        pad = BORDER_PX if self.args.no_titlebar else 0
        bg  = self.args.bg
        fg  = self.args.fg

        outer = tk.Frame(
            self.root, bg=self.root.cget("bg"), bd=0, highlightthickness=0
        )
        outer.pack(fill="both", expand=True, padx=pad, pady=pad)

        # ── Tempo list panel (packed FIRST so side='bottom' claim wins) ──────
        # The pill canvas must be packed before top_frame, because tkinter
        # allocates space in packing order.  If top_frame (expand=True) is
        # packed first, it consumes all remaining space and the pill canvas
        # is left with zero pixels regardless of side='bottom'.
        self._create_list_panel(outer, bg)

        # ── Top area (canvas + buttons) ───────────────────────────────────────
        top_frame = tk.Frame(outer, bg=self.root.cget("bg"), bd=0,
                             highlightthickness=0)
        top_frame.pack(side="top", fill="both", expand=True)

        # ── Button column ─────────────────────────────────────────────────────
        btn_frame = tk.Frame(
            top_frame, bg=bg, width=BTN_COL_W, bd=0, highlightthickness=0
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
        sep = tk.Frame(top_frame, bg=SEP_COLOR, width=1, bd=0, highlightthickness=0)
        sep.pack(side="right", fill="y")

        # ── Canvas (indicator + big text) ─────────────────────────────────────
        self.canvas = tk.Canvas(top_frame, bg=bg, highlightthickness=0)
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
            self.context_menu.add_command(label="Quit",   command=self._on_close)
            self.context_menu.add_separator()
            self.context_menu.add_command(label="Cancel", command=lambda: None)

        # Double-click on the main canvas appends the current BPM to the list
        self.canvas.bind("<Double-Button-1>", lambda e: self._gui_list_append())

        # Mouse-wheel scroll on the main canvas adjusts BPM
        self.canvas.bind("<Button-4>",  lambda e: self._scroll_bpm(+1))
        self.canvas.bind("<Button-5>",  lambda e: self._scroll_bpm(-1))
        self.canvas.bind("<MouseWheel>",
                         lambda e: self._scroll_bpm(+1 if e.delta > 0 else -1))

        # Pill canvas scroll: dispatch to the pill under the cursor (to edit
        # that entry) or fall back to global BPM scroll over empty space.
        # Canvas item tag_bind rejects <Button-4/5>, so we handle it at the
        # canvas-widget level and use find_overlapping to pick the right pill.
        self._pill_canvas.bind(
            "<Button-4>",   lambda e: self._pill_canvas_scroll(e, +1))
        self._pill_canvas.bind(
            "<Button-5>",   lambda e: self._pill_canvas_scroll(e, -1))
        self._pill_canvas.bind(
            "<MouseWheel>",
            lambda e: self._pill_canvas_scroll(e, +1 if e.delta > 0 else -1))

        # (tempo list panel already created above)

    # ── Tempo list panel ───────────────────────────────────────────────────────
    def _create_list_panel(self, parent: tk.Frame, bg: str) -> None:
        """
        Create the pill-row canvas that lives below the main display.

        A tk.Canvas with an explicit height is used instead of a Frame
        containing Label widgets.  A canvas with height=H *always* occupies
        exactly H pixels regardless of pack-manager state, which eliminates
        the layout-measurement races that plagued the Label approach.
        """
        self._pill_canvas = tk.Canvas(
            parent,
            height=0,          # starts collapsed
            bg=bg,
            bd=0,
            highlightthickness=0,
        )
        # Pack at the bottom – this ensures the pack manager allocates the
        # canvas its configured height BEFORE giving top_frame its expand bonus.
        # With side="top", top_frame's expand=True would eat all extra space
        # and compress the canvas to zero pixels.
        self._pill_canvas.pack(side="bottom", fill="x")
        self._panel_visible: bool          = False
        self._pill_item_to_index: dict[int, int] = {}  # canvas item id → pill index
        self._active_pill_text_id: int | None    = None  # text item of the active pill

    def _fast_update_active_pill(self, bpm: float) -> bool:
        """
        Update only the active pill's label text without a full redraw.

        Called on every rapid BPM change (hold-repeat, JACK adoption) to
        avoid the expensive ``delete("all")`` + redraw + ``tag_bind`` cycle
        that ``_refresh_list_panel`` performs.  Returns ``True`` on success;
        ``False`` if the item no longer exists or the panel is not visible,
        in which case the caller should fall back to ``_refresh_list_panel``.
        """
        if not self._panel_visible or self._active_pill_text_id is None:
            return False
        label = f"{bpm:.{self.args.precision}f}"
        try:
            self._pill_canvas.itemconfig(self._active_pill_text_id, text=label)
            return True
        except Exception:
            return False   # stale item id; caller will do a full redraw

    def _refresh_list_panel(self) -> None:
        """
        Redraw the pill canvas to reflect the current TempoList state.

        When empty: canvas height → 0 (invisible, takes no space).
        When non-empty: canvas height → LIST_PANEL_H; pills are drawn
        as filled rectangles with text overlaid directly on the canvas.
        """
        import tkinter.font as _tf
        tempos = self._tempo_list.tempos
        idx    = self._tempo_list.index

        self._pill_canvas.delete("all")
        self._pill_item_to_index  = {}    # rebuild on every redraw
        self._active_pill_text_id = None  # reset; set below for the active pill

        if not tempos:
            if self._panel_visible:
                self._pill_canvas.configure(height=0)
                self._panel_visible = False
                self._resize_to_content()
            return

        # Expand the canvas when first showing
        if not self._panel_visible:
            self._pill_canvas.configure(height=LIST_PANEL_H)
            self._panel_visible = True
            self._resize_to_content()

        # Measure font so we can size pills accurately
        font_obj = _tf.Font(family=FONT_FAMILY, size=LIST_PILL_FONT_SIZE)

        # Draw separator line along the top edge
        self._pill_canvas.create_line(
            0, 0, 9999, 0, fill=LIST_SEP_COLOR, width=1
        )

        # Draw pills left-to-right
        x = LIST_PILL_GAP
        cy = LIST_PANEL_H // 2          # vertical center of canvas
        pill_h = LIST_PILL_FONT_SIZE + LIST_PILL_PAD_Y * 2 + 4
        y0 = cy - pill_h // 2
        y1 = cy + pill_h // 2

        for i, bpm in enumerate(tempos):
            active = (i == idx)
            label  = f"{bpm:.{self.args.precision}f}"
            tw     = font_obj.measure(label)
            x1     = x + tw + LIST_PILL_PAD_X * 2
            tag    = f"pill_{i}"

            # Pill background rectangle
            rect_id = self._pill_canvas.create_rectangle(
                x, y0, x1, y1,
                fill=LIST_PILL_ACT_BG if active else LIST_PILL_BG,
                outline="",
                tags=(tag,),
            )
            # Pill text
            text_id = self._pill_canvas.create_text(
                x + LIST_PILL_PAD_X, cy,
                text=label,
                anchor="w",
                fill=LIST_PILL_ACT_FG if active else LIST_PILL_FG,
                font=(FONT_FAMILY, LIST_PILL_FONT_SIZE),
                tags=(tag,),
            )
            # Register both items so the canvas-level scroll dispatcher can
            # identify which pill the cursor is over (tag_bind rejects Button-4/5)
            self._pill_item_to_index[rect_id] = i
            self._pill_item_to_index[text_id] = i
            if active:
                self._active_pill_text_id = text_id

            x = x1 + LIST_PILL_GAP

            # Bind interactions for this pill
            self._pill_canvas.tag_bind(
                tag, "<Button-1>",
                lambda e, idx_=i: self._gui_pill_select(idx_),
            )
            self._pill_canvas.tag_bind(
                tag, "<Button-2>",
                lambda e, idx_=i: self._gui_pill_remove(idx_),
            )
            self._pill_canvas.tag_bind(
                tag, "<Button-3>",
                lambda e, idx_=i: self._gui_pill_context(e, idx_),
            )
            self._pill_canvas.tag_bind(
                tag, "<Enter>",
                lambda e: self._pill_canvas.configure(cursor="hand2"),
            )
            self._pill_canvas.tag_bind(
                tag, "<Leave>",
                lambda e: self._pill_canvas.configure(cursor=""),
            )

    def _resize_to_content(self) -> None:
        """
        Resize the root window to show or hide the tempo list panel.

        Uses the fixed constant LIST_PANEL_H rather than measuring the
        panel at runtime.  Measuring via winfo_reqheight() is unreliable
        because the pack geometry manager may not have settled yet, causing
        near-zero readings and the panel appearing invisible even though the
        pills have been packed.  LIST_PANEL_H is sized to match the 14pt
        font plus padding used by the pills.
        """
        cur_w    = self.root.winfo_width()
        use_w    = self._base_win_w if cur_w < 2 else cur_w
        target_h = (self._base_win_h + 1 + LIST_PANEL_H
                    if self._panel_visible else self._base_win_h)
        self.root.geometry(f"{use_w}x{target_h}")
        self._dbg(f"_resize_to_content: {use_w}x{target_h}")

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

    # ── Quantize-jack send ─────────────────────────────────────────────────────
    def _fire_on_quantize(self) -> None:
        """
        Fire ``send.on_quantize`` actions when ``quantize_jack`` has snapped a
        JACK-adopted tempo to a grid value.

        This is intentionally separate from ``on_change`` (which only fires
        for user-initiated changes) so that the two triggers can be routed
        independently – e.g. silence ``on_change`` but still push snapped
        tempos back to Hydrogen via OSC.
        """
        self._dbg(
            f"_fire_on_quantize: sending quantized BPM {self.current_bpm:.3f}"
        )
        self._fire_send("on_quantize", bpm=self.current_bpm, raw=0)

    # ── Transport change handler ───────────────────────────────────────────────
    def _on_transport_change(self, rolling: bool) -> None:
        """
        Called on every JACK transport state transition.

        Fires ``send`` entries keyed by:
        - ``"transport_start"``  – when transport begins rolling
        - ``"transport_stop"``   – when transport stops
        - ``"transport_toggle"`` – on either transition
        """
        rolling_int = 1 if rolling else 0
        direction   = "transport_start" if rolling else "transport_stop"
        self._dbg(f"transport change → {direction} (rolling={rolling_int})")
        for trigger in (direction, "transport_toggle"):
            self._fire_send(trigger, bpm=self.current_bpm, raw=0, rolling=rolling_int)

    # ── Main update loop ───────────────────────────────────────────────────────
    def _update_loop(self) -> None:
        # 0. Drain MIDI event queue ────────────────────────────────────────────
        # The mididings JACK process callback puts events on a SimpleQueue
        # instead of calling root.after() directly, avoiding Tcl calls and
        # GIL contention in the RT thread.  We drain here, before the JACK
        # transport query, so that user MIDI changes to current_bpm and
        # _last_user_time are visible when the JACK adoption logic runs.
        for action, amount, raw, send_specs in self.midi.drain():
            self._on_midi_receive(action, amount, raw, send_specs)

        # 1. Config hot-reload ─────────────────────────────────────────────────
        self._check_config_reload()

        # 1. Poll JACK ─────────────────────────────────────────────────────────
        if self.jack_client:
            try:
                state, pos = self.jack_client.transport_query()
                self._rolling = (state == jack.ROLLING)

                # Detect start/stop edges (skip on the very first poll)
                if self._prev_rolling is None:
                    self._prev_rolling = self._rolling
                elif self._rolling != self._prev_rolling:
                    self._prev_rolling = self._rolling
                    self._on_transport_change(self._rolling)

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
                            adopted   = jack_bpm
                            quantized = False
                            if self.cfg.get("quantize_jack", False):
                                snapped = quantize_bpm(adopted, self.cfg)
                                if abs(snapped - adopted) > 1e-6:
                                    quantized = True
                                    self._dbg(
                                        f"JACK adopt: raw={jack_bpm:.3f}"
                                        f"  quantized={snapped:.3f}"
                                    )
                                adopted = snapped
                            self.current_bpm = self._clamp(adopted)
                            # Mirror the list_update_on_change behavior from
                            # _user_set_bpm: keep the active list slot in sync
                            # with JACK-adopted tempos the same way it tracks
                            # user-initiated changes.
                            if self.cfg.get("list_update_on_change", True):
                                if self._tempo_list.replace_current(self.current_bpm):
                                    self._dbg(
                                        f"JACK adopt list_update: slot "
                                        f"{self._tempo_list.index} "
                                        f"→ {self.current_bpm:.3f}"
                                    )
                                    if not self._fast_update_active_pill(self.current_bpm):
                                        self._refresh_list_panel()
                            if quantized:
                                self._fire_on_quantize()

            except Exception as exc:
                print(f"JACK query error: {exc}", file=sys.stderr)

        # 2. Render ────────────────────────────────────────────────────────────
        cw, ch  = self.canvas.winfo_width(), self.canvas.winfo_height()
        display = f"{self.current_bpm:.{self.args.precision}f}"
        clr     = COLOR_ROLLING if self._rolling else COLOR_IDLE

        if (display != self._last_display
                or clr != self._last_clr
                or (cw, ch) != self._last_canvas_size):

            self.canvas.itemconfig(self.text, text=display)
            self.canvas.itemconfig(self.box,  fill=clr, outline=clr)

            self.root.update_idletasks()
            # Re-query after idletasks in case a resize was pending
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

            self._last_display     = display
            self._last_clr         = clr
            self._last_canvas_size = (cw, ch)

        self.root.after(self.update_ms, self._update_loop)
