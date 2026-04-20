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
#                     buttons, debug, OSC host/port.
# Requires restart:   midi.client_name (JACK client rename not supported).
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
    # Set to True to print a full trace of every BPM change and OSC/MIDI send
    # to stderr.  Turn off again once everything is working.
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
    "quantize":      None,
    "quantize_jack": False,  # set True to also quantize JACK-adopted tempos

    # ── Incoming MIDI CC mappings ──────────────────────────────────────────────
    # Key format: "CC<number>"
    #
    # BPM actions:
    #   up        – raise BPM by <amount>
    #   down      – lower BPM by <amount>
    #   set       – proportionally map the incoming CC value (0-127) onto the
    #               min_bpm-max_bpm range for an absolute tempo set.
    #               CC=0 → min_bpm, CC=127 → max_bpm, CC=64 → midpoint.
    #               The raw 0-127 value is NOT used directly as a BPM number.
    #
    # Tempo list actions:
    #   list_append – save current BPM to end of tempo list
    #   list_next   – step to next saved tempo cyclically and apply it
    #   list_clear  – discard all saved tempos and reset the pointer
    #
    # Send-only actions (fire a send without changing BPM):
    #   osc_only  – fire the entry's osc_send without changing tempo
    #   midi_only – fire the entry's midi_send without changing tempo
    #
    # Any receive entry may also carry an "osc_send" and/or "midi_send" key to
    # fire additional messages alongside (or instead of) its BPM action.
    "receive": {
        "CC20": {"action": "up",          "amount": 1.0},
        "CC21": {"action": "down",        "amount": 1.0},
        "CC22": {"action": "set"},
        "CC23": {"action": "list_append"},
        "CC24": {"action": "list_next"},
        "CC25": {"action": "list_clear"},

        # Trigger Hydrogen PLAY via OSC – no BPM change
        # "CC26": {"action": "osc_only",
        #          "osc_send": {"address": "/Hydrogen/PLAY", "args": []}},

        # Fire a fixed CC value (e.g. to trigger a DAW mute) – no BPM change
        # "CC27": {"action": "midi_only",
        #          "midi_send": {"cc": 50, "channel": 2, "value": 127}},

        # Up press that also logs BPM + raw value over OSC
        # "CC20": {"action": "up", "amount": 1.0,
        #          "osc_send": {"address": "/log/bpm_up", "args": ["bpm", "raw"]}},
    },

    # ── Outgoing MIDI CC ──────────────────────────────────────────────────────
    # Fires on every user-initiated BPM change (buttons, incoming MIDI, list_next).
    # JACK-initiated changes do NOT trigger a send.
    #
    # "value" is REQUIRED in every midi_send spec.  Omitting it prints a
    # warning to stderr and skips that send entirely.  Valid values:
    #   "bpm"       – current BPM mapped proportionally to 0-127
    #   "raw"       – pass the incoming CC value straight through (0-127)
    #   "rolling"   – 127 on transport start, 0 on transport stop
    #   <int 0-127> – fixed literal
    "midi_send": {
        # "on_change":   {"cc": 30, "channel": 1, "value": "bpm"},
        # "on_quantize": {"cc": 30, "channel": 1, "value": "bpm"},  # fires when quantize_jack snaps a tempo
        # "on_change": {"cc": 31, "channel": 1, "value": 64},     # always 64
        #
        # JACK transport events:
        # "transport_start":  {"cc": 32, "channel": 1, "value": 127},
        # "transport_stop":   {"cc": 32, "channel": 1, "value": 0},
        # "transport_toggle": {"cc": 33, "channel": 1, "value": "rolling"},
    },

    # ── OSC connection settings ────────────────────────────────────────────────
    # Required if any osc_send is used.  Defines a single UDP destination.
    "osc": {
        "host": "127.0.0.1",    # destination host (usually localhost)
        "port": 9000,            # Hydrogen OSC port (Edit → Preferences → OSC)
    },

    # ── Outgoing OSC messages ──────────────────────────────────────────────────
    # "on_change" fires on every user-initiated BPM change.
    #
    # This is the recommended way to drive Hydrogen's tempo: its MIDI
    # interface only supports relative BPM changes (±63 BPM max), while its
    # OSC interface accepts an absolute float – no drift, no ambiguity.
    #
    # "args" tokens:
    #   "bpm"       – current BPM as a float
    #   "raw"       – incoming CC value 0-127 as an int
    #   <literal>   – passed through unchanged (int, float, str, bool)
    "osc_send": {
        "on_change":   {"address": "/Hydrogen/BPM", "args": ["bpm"]},
        # "on_quantize": {"address": "/Hydrogen/BPM", "args": ["bpm"]},
        #   Fires when quantize_jack snaps a JACK-adopted tempo (e.g. tap-tempo).
        #   Use this to push the snapped value back to Hydrogen over OSC.
        #   Unlike on_change, this does NOT fire for user-initiated changes.
        # Additional fixed messages fired on every change:
        # "on_change_also": [
        #     {"address": "/some/other/thing", "args": [1]},
        # ],
        #
        # JACK transport events:
        # "transport_start":  {"address": "/Hydrogen/PLAY",  "args": []},
        # "transport_stop":   {"address": "/Hydrogen/PAUSE", "args": []},
        # "transport_toggle": {"address": "/transport",      "args": ["rolling"]},
        #   "rolling" token → 1 on start, 0 on stop
    },
}
