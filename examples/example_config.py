# big-tempo configuration
# Copy to ~/.config/big-tempo/config.py and edit to taste.
#
# This file is parsed as a Python dict literal via ast.literal_eval.
# Full Python comment syntax is supported.  Trailing commas are fine.
# Arbitrary code is NOT executed – only data literals are accepted.
#
# HOT RELOAD: this file is watched while big-tempo is running.  Save it
# and changes take effect within one update tick (~100 ms by default).
# A timestamped notice is printed to the terminal on each reload.
#
# What reloads live:  all receive/send mappings, min/max BPM, quantize,
#                     buttons, tempo-list behavior, debug, OSC targets.
# Requires restart:   midi.client_name (JACK client rename not supported),
#                     tempo_list (read only at startup).
{
    "midi": {
        "client_name": "big_tempo_midi",
        "channel": 1,
    },

    "buttons": {
        "increment": 1.0,           # BPM added or removed per click / repeat tick
        "repeat_delay_ms": 400,     # ms before hold-repeat kicks in
        "repeat_ms": 80,            # ms between repeat ticks while held
    },

    # ── Debug mode ────────────────────────────────────────────────────────────
    # Set to True to print a full trace of every incoming CC, BPM change, and
    # outgoing MIDI / OSC send to stderr.  Turn off once everything is working.
    "debug": False,

    "min_bpm": 20.0,
    "max_bpm": 300.0,

    # ── Tempo quantization ────────────────────────────────────────────────────
    # Snap BPM changes to the nearest multiple of this value.
    # "quantize"      applies to user-initiated changes (buttons, incoming MIDI).
    # "quantize_jack" also applies the same step to JACK-adopted tempos
    #                 (e.g. Hydrogen tap-tempo → snap to nearest integer).
    #
    # Examples:
    #   1.0   → integers only     (120, 121, 122 …)
    #   0.5   → half-BPM steps   (120.0, 120.5, 121.0 …)
    #   0.25  → quarter-BPM      (120.0, 120.25, 120.5 …)
    #   5.0   → 5-BPM steps      (120, 125, 130 …)
    #   None  → disabled (allow any float, default)
    "quantize":               None,
    "quantize_jack":          False,  # set True to also quantize JACK-adopted tempos

    # ── Tempo list: update current slot on BPM change ─────────────────────────
    # When True (default), any user-initiated BPM change while a tempo list
    # entry is active overwrites that entry with the new value.  Useful for
    # nudging a saved tempo on the fly.  Set to False to keep saved tempos fixed.
    "list_update_on_change":  True,

    # ── Tempo list: activate a slot as soon as it is added ────────────────────
    # When True, saving a tempo (list_append or double-click) immediately makes
    # the new entry the active one, so further BPM nudges edit it in place and
    # list_next advances from it.  When False (default), appended tempos are
    # saved but the pointer stays where it was until you switch to the list.
    "activate_on_append":     False,

    # ── Tempo list: preload at startup ────────────────────────────────────────
    # Tempos to load into the list when big-tempo starts, e.g. a set list:
    # [92, 104, 120].  None is active, so the display follows JACK until the
    # first list_next / list_prev.  Read only at startup: a reload never
    # discards tempos appended or adjusted while playing.
    "tempo_list":             [],

    # ── Incoming MIDI CC mappings ──────────────────────────────────────────────
    # Key format: "CC<number>"  (CC number 0–127)
    #
    # BPM actions:
    #   up        – raise BPM by <amount>
    #   down      – lower BPM by <amount>
    #   set       – proportionally map the incoming CC value (0-127) onto the
    #               min_bpm–max_bpm range.  CC=0 → min_bpm, CC=127 → max_bpm.
    #               The raw 0–127 value is NOT used directly as a BPM number.
    #
    # Tempo list actions:
    #   list_append – save current BPM to end of tempo list
    #   list_next   – step to next saved tempo cyclically and apply it
    #   list_prev   – step to previous saved tempo cyclically and apply it
    #   list_clear  – discard all saved tempos and reset the pointer
    #
    # Send-only actions (fire a "send" list without changing BPM):
    #   osc_only  – fire the entry's "send" list, no BPM change
    #   midi_only – fire the entry's "send" list, no BPM change
    #
    # Any receive entry may carry a "send" list to fire additional MIDI and/or
    # OSC messages alongside (or instead of) its BPM action.  See the outgoing
    # "send" section below for the action dict format.
    "receive": {
        "CC20": {"action": "up",          "amount": 1.0},
        "CC21": {"action": "down",        "amount": 1.0},
        "CC22": {"action": "set"},
        "CC23": {"action": "list_append"},
        "CC24": {"action": "list_next"},
        "CC25": {"action": "list_prev"},
        "CC26": {"action": "list_clear"},

        # Trigger Hydrogen PLAY via OSC – no BPM change
        "CC27": {"action": "osc_only",
                 "send": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                           "address": "/Hydrogen/PLAY", "args": []}]},

        # Fire a fixed CC value (e.g. to trigger a DAW mute) – no BPM change
        "CC28": {"action": "midi_only",
                 "send": [{"send": "MIDI", "cc": 50, "channel": 2, "value": 127}]},

        # A second "up" press (on its own CC) that also logs BPM + raw
        # value over OSC, showing a "send" list attached to a BPM action
        "CC29": {"action": "up", "amount": 1.0,
                 "send": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                           "address": "/log/bpm_up", "args": ["bpm", "raw"]}]},
    },

    # ── Outgoing sends ─────────────────────────────────────────────────────────
    # Maps trigger names to a list of action dicts.  Every action dict must
    # carry a "send" key of "MIDI" or "OSC".
    #
    # Multiple actions on one trigger fire in list order, so you can mix MIDI
    # and OSC freely, or fan out to several OSC targets at once.
    #
    # MIDI action keys:
    #   "send":    "MIDI"          (required discriminator)
    #   "cc":      <int 0–127>     (required)
    #   "channel": <int 1–16>      (required)
    #   "value":   "bpm"           – current BPM mapped proportionally to 0–127
    #              "raw"           – incoming CC value passed straight through
    #              "rolling"       – 127 on transport start, 0 on transport stop
    #              <int 0–127>     – fixed literal value
    #
    # OSC action keys:
    #   "send":    "OSC"           (required discriminator)
    #   "host":    <string>        (required – destination IP or hostname)
    #   "port":    <int 1–65535>   (required – destination UDP port)
    #   "address": <string>        (required – must start with '/')
    #   "args":    [token, …]      (optional list; same tokens as "value" above,
    #                               plus any literal int / float / str / bool)
    #
    # Trigger names:
    #   on_change        – every user-initiated BPM change (buttons, MIDI, list_next)
    #   on_quantize      – when quantize_jack snaps a JACK-adopted tempo to the grid
    #   transport_start  – JACK transport starts rolling
    #   transport_stop   – JACK transport stops
    #   transport_toggle – either transport transition
    "send": {
        # ── on_change: push new tempo to Hydrogen on every user change ─────────
        # Also shows fan-out (a second OSC target) and mixing MIDI with OSC
        # on the same trigger.
        "on_change": [
            {"send": "OSC", "host": "127.0.0.1", "port": 9000,
             "address": "/Hydrogen/BPM", "args": ["bpm"]},
            {"send": "OSC", "host": "10.0.0.5",  "port": 7400,
             "address": "/stage/bpm",    "args": ["bpm"]},
            {"send": "MIDI", "cc": 30, "channel": 1, "value": "bpm"},
        ],

        # ── on_quantize: push snapped tempo back to Hydrogen ──────────────────
        # Fires when quantize_jack corrects a JACK-adopted tempo.  Unlike
        # on_change this does NOT fire for user-initiated changes.
        "on_quantize": [
            {"send": "OSC", "host": "127.0.0.1", "port": 9000,
             "address": "/Hydrogen/BPM", "args": ["bpm"]},
        ],

        # ── JACK transport events ─────────────────────────────────────────────
        "transport_start": [
            {"send": "OSC",  "host": "127.0.0.1", "port": 9000,
             "address": "/Hydrogen/PLAY", "args": []},
            {"send": "MIDI", "cc": 32, "channel": 1, "value": 127},
        ],
        "transport_stop": [
            {"send": "OSC",  "host": "127.0.0.1", "port": 9000,
             "address": "/Hydrogen/PAUSE", "args": []},
            {"send": "MIDI", "cc": 32, "channel": 1, "value": 0},
        ],
        "transport_toggle": [
            # "rolling" token → 1 on start, 0 on stop
            {"send": "MIDI", "cc": 33, "channel": 1, "value": "rolling"},
        ],
    },
}
