big-tempo
=========

A minimalist JACK tempo display with MIDI control via **mididings** and OSC
output via **python-osc**.

.. code-block:: text

    ┌──────────────────────────────────┬──────────┐
    │  ●  120.0                        │    ▲     │
    │                                  │    ▼     │
    └──────────────────────────────────┴──────────┘


Features
--------

- Large BPM readout that auto-scales to the window size
- JACK transport rolling indicator (grey → red)
- **▲ / ▼ buttons** with configurable hold-to-repeat
- **mididings MIDI I/O** (JACK MIDI backend)

  - Receive CC to increment, decrement, or set BPM
  - Outgoing MIDI CC on user-initiated changes, with configurable value encoding

- **python-osc OSC output** for absolute tempo commands (recommended for
  Hydrogen, which only supports relative BPM over MIDI)
- **Unified send lists** – each trigger maps to a list of MIDI and/or OSC
  action dicts, so you can fan out to multiple destinations in one config line
- **Tempo list** – save BPM snapshots during soundcheck and cycle through
  them live via a single footswitch; also fully controllable from the mouse
  (double-click to append, click a pill to jump, middle-click to remove,
  scroll wheel to nudge BPM)
- Per-receive send lists – any incoming CC can fire extra MIDI and OSC
  messages independently of its BPM action
- Adopts JACK tempo changes from an external master (e.g. Hydrogen)
  without firing outgoing MIDI or OSC


Requirements
------------

.. list-table::
   :header-rows: 1
   :widths: 20 50

   * - Requirement
     - Notes
   * - Python ≥ 3.9
     -
   * - tkinter
     - Usually bundled with Python; ``python3-tk`` on Debian/Ubuntu
   * - ``JACK-Client``
     - ``pip install JACK-Client`` or distro package ``python3-jack``
   * - ``mididings``
     - ``pip install mididings`` or distro package ``python3-mididings``
   * - ``python-osc``
     - Included in ``pip install -e .`` (pure Python, no C extensions)

``jack`` and ``mididings`` are **optional** at runtime – the app starts without
them and degrades gracefully with a one-time warning to stderr.  ``python-osc``
is a hard dependency and is installed automatically.


Installation
------------

``JACK-Client`` and ``mididings`` link against C libraries (``libjack`` and
ALSA) that pip cannot build automatically.  Install the system libraries and
their Python bindings **before** running ``pip install -e .``::

    # Debian / Ubuntu – recommended path
    sudo apt install python3-jack python3-mididings python3-tk

    # Alternative: install C libs via apt, then Python wrappers via pip
    sudo apt install libjack-jackd2-dev python3-tk
    pip install JACK-Client mididings

Then install the package (``python-osc`` is pulled in automatically)::

    pip install -e .

For development (adds pytest)::

    pip install -e ".[dev]"

.. note::

   If ``pip install -e .`` fails with a build error for ``JACK-Client`` or
   ``mididings``, install those two packages manually first (see above) and
   then re-run ``pip install -e .``.


Running
-------

.. code-block:: bash

    big-tempo                          # uses ~/.config/big-tempo/config.py
    big-tempo --config my_config.py
    big-tempo --no-titlebar --always-on-top
    python -m big_tempo                # also works

All CLI options::

    --config PATH         Python dict literal config file
    --width-in FLOAT      Window width in inches
    --height-in FLOAT     Window height in inches
    --update-ms INT       JACK poll interval in milliseconds
    --font-size INT       Fixed font size in points (overrides auto-fit)
    --precision INT       Decimal places shown in BPM readout
    --bg COLOR            Background colour (default: white)
    --fg COLOR            Foreground colour (default: black)
    --always-on-top       Keep window above all others
    --no-titlebar         Remove title bar; enables click-drag to move
    --save-pos [FILE]     Save the window position on exit and restore it on
                          the next run.  With no argument, uses
                          ~/.config/big-tempo/window.pos.  Pass an explicit
                          path when running multiple configs that need
                          separate positions.


Config file
-----------

Default location: ``~/.config/big-tempo/config.py``

The file must contain a single Python **dict literal**.  Full ``#`` comment
syntax and trailing commas are supported (unlike JSON).  It is parsed with
``ast.literal_eval`` – no arbitrary code is executed.

A fully annotated starter file is provided as ``examples/example_config.py``
in the repository root::

    mkdir -p ~/.config/big-tempo
    cp examples/example_config.py ~/.config/big-tempo/config.py

The loader validates the config on every load and reload.  Problems (unknown
action names, missing required keys, out-of-range values, legacy key names)
are printed to stderr as ``Config warning:`` lines.  The config is still
applied – warnings are informational, not fatal.

Hot reload
~~~~~~~~~~

The config file is **reloaded automatically while the program is running**.
Every update tick (default 100 ms) big-tempo checks the file's modification
time.  If it has changed, the new config is parsed and applied immediately –
no restart needed.

A timestamped message is printed to stderr on each reload::

    [14:32:07] config reloaded: /home/user/.config/big-tempo/config.py

**What takes effect immediately:**

- All ``receive`` and ``send`` mappings
- ``min_bpm``, ``max_bpm``, ``quantize``, ``quantize_jack``
- ``buttons`` timing (increment, repeat delay/rate)
- ``debug`` flag
- OSC targets (the send pool is rebuilt fresh on each reload)

**Requires a restart:**

- ``midi.client_name`` – the mididings JACK client cannot be renamed
  at runtime; a note is printed alongside the reload message if this key
  was changed.

Top-level structure::

    {
        "midi":    {"client_name": "big_tempo_midi", "channel": 1},
        "buttons": {"increment": 1.0, "repeat_delay_ms": 400, "repeat_ms": 80},
        "min_bpm": 20.0,
        "max_bpm": 300.0,
        "receive": { ... },   # incoming CC → BPM action + optional sends
        "send":    { ... },   # trigger → list of MIDI / OSC action dicts
    }


Receive actions
~~~~~~~~~~~~~~~

``"receive"`` maps CC numbers (``"CC<n>"``) to action dicts.

.. list-table::
   :header-rows: 1
   :widths: 15 55

   * - Action
     - Effect
   * - ``up``
     - Add ``amount`` BPM
   * - ``down``
     - Subtract ``amount`` BPM
   * - ``set``
     - Proportionally map the incoming CC value (0–127) onto the
       ``min_bpm``–``max_bpm`` range.  CC=0 → ``min_bpm``, CC=127 →
       ``max_bpm``, CC=64 → midpoint.  The raw value is **not** used
       directly as a BPM number.
   * - ``list_append``
     - Save the current BPM to the end of the tempo list
   * - ``list_next``
     - Advance the tempo-list pointer one step (wrapping), apply that BPM,
       and fire outgoing sends
   * - ``list_clear``
     - Discard all saved tempos and reset the list pointer
   * - ``osc_only``
     - Fire the entry's ``"send"`` list without changing tempo
   * - ``midi_only``
     - Fire the entry's ``"send"`` list without changing tempo

Any receive entry may carry a ``"send"`` list to fire extra MIDI and/or OSC
messages alongside its primary action::

    "receive": {
        # BPM up + log over OSC
        "CC20": {"action": "up", "amount": 1.0,
                 "send": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                           "address": "/log/up", "args": ["bpm", "raw"]}]},

        # Trigger Hydrogen PLAY – no BPM change
        "CC26": {"action": "osc_only",
                 "send": [{"send": "OSC", "host": "127.0.0.1", "port": 9000,
                           "address": "/Hydrogen/PLAY", "args": []}]},

        # Fire a fixed CC to a DAW – no BPM change
        "CC27": {"action": "midi_only",
                 "send": [{"send": "MIDI", "cc": 50, "channel": 2, "value": 127}]},
    },


Unified send lists (``send``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``"send"`` maps trigger names to a **list** of action dicts.  Actions fire in
list order; MIDI and OSC actions may be freely mixed on the same trigger.  The
same OSC host/port can appear on multiple triggers – a single UDP socket is
reused per unique ``(host, port)`` pair.

**Trigger names:**

.. list-table::
   :header-rows: 1
   :widths: 18 52

   * - Trigger
     - When it fires
   * - ``on_change``
     - Every user-initiated BPM change (buttons, incoming MIDI, ``list_next``)
   * - ``on_quantize``
     - When ``quantize_jack`` snaps a JACK-adopted tempo to the grid and the
       snapped value differs from the raw value.  Use this to push the
       corrected tempo back to Hydrogen without also re-sending on every user
       button press.
   * - ``transport_start``
     - JACK transport transitions from stopped to rolling
   * - ``transport_stop``
     - JACK transport transitions from rolling to stopped
   * - ``transport_toggle``
     - Either transport transition

**MIDI action keys:**

.. list-table::
   :header-rows: 1
   :widths: 12 12 46

   * - Key
     - Required
     - Value
   * - ``"send"``
     - yes
     - ``"MIDI"``
   * - ``"cc"``
     - yes
     - Integer 0–127
   * - ``"channel"``
     - yes
     - Integer 1–16
   * - ``"value"``
     - yes
     - ``"bpm"`` – current BPM mapped proportionally to 0–127 |br|
       ``"raw"`` – incoming CC value passed straight through (0–127) |br|
       ``"rolling"`` – 127 on transport start, 0 on transport stop |br|
       ``<int 0–127>`` – fixed literal

.. |br| raw:: html

   <br />

**OSC action keys:**

.. list-table::
   :header-rows: 1
   :widths: 12 12 46

   * - Key
     - Required
     - Value
   * - ``"send"``
     - yes
     - ``"OSC"``
   * - ``"host"``
     - yes
     - Destination hostname or IP address
   * - ``"port"``
     - yes
     - Destination UDP port (1–65535)
   * - ``"address"``
     - yes
     - OSC address string starting with ``/``
   * - ``"args"``
     - no
     - List of tokens and/or literals.  Token strings: ``"bpm"`` (float),
       ``"raw"`` (int), ``"rolling"`` (int).  Any other value is passed
       through unchanged (int, float, str, bool).

**Example – Hydrogen tempo + transport:**

.. code-block:: python

    "send": {
        "on_change": [
            {"send": "OSC", "host": "127.0.0.1", "port": 9000,
             "address": "/Hydrogen/BPM", "args": ["bpm"]},
        ],
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
    },

**Example – fan out to two OSC destinations:**

.. code-block:: python

    "send": {
        "on_change": [
            {"send": "OSC", "host": "127.0.0.1", "port": 9000,
             "address": "/Hydrogen/BPM", "args": ["bpm"]},
            {"send": "OSC", "host": "10.0.0.5",  "port": 7400,
             "address": "/stage/bpm",    "args": ["bpm"]},
        ],
    },


Tempo list
~~~~~~~~~~

Save a set of BPM values during soundcheck and cycle through them live::

    # Soundcheck: dial each song's tempo, then:
    CC23  →  list_append   (repeat for each song)

    # Performance: one stomp per song to change tempo
    CC24  →  list_next     (wraps back to first entry after the last)

    # End of night
    CC25  →  list_clear

The pointer starts before the first entry.  The first ``list_next`` always
recalls the first saved tempo.  Appending during a cycle extends the list
without disturbing the current position.

**Mouse control (no MIDI controller needed)**

The tempo list is also fully operable from the mouse:

.. list-table::
   :header-rows: 1
   :widths: 28 42

   * - Gesture
     - Effect
   * - Double-click the BPM display
     - Append current BPM to the list
   * - Single-click a pill
     - Jump directly to that tempo and activate it
   * - Middle-click a pill
     - Remove that entry from the list
   * - Right-click a pill
     - Context menu: *Switch to this tempo* / *Remove from list*
   * - Scroll wheel (display or pill row)
     - Nudge BPM up / down by ``buttons.increment``

Pills grow a hand cursor on hover.  When the last entry is removed the pill
row collapses automatically.

**Pointer behaviour when removing a pill**

- Removing the **active** entry moves to the next one (wrapping to the first
  if the removed entry was last).
- Removing an **inactive** entry before the active one shifts the pointer
  back by one so the same entry stays active.
- Removing an **inactive** entry after the active one leaves the pointer
  unchanged.

**Editing a saved tempo live** – by default (``"list_update_on_change": True``),
any user-initiated BPM change (button press, incoming MIDI, or scroll wheel)
while a tempo list entry is active overwrites that entry with the new value.
The pill display updates immediately.  This lets you nudge a saved tempo on
the fly without having to clear and re-capture.  Set the option to ``False``
if you want saved tempos to stay fixed once captured.

Button hold-repeat
~~~~~~~~~~~~~~~~~~

Holding ▲ or ▼ fires one tick immediately, then waits ``repeat_delay_ms``
before entering a fast repeat loop at ``repeat_ms`` per tick.


Development
-----------

.. code-block:: bash

    # Run the full test suite (no JACK, MIDI hardware, or display required)
    pytest

    # With coverage report
    pytest --cov=big_tempo --cov-report=term-missing

All hardware dependencies (``jack``, ``mididings``, ``python-osc``) are
stubbed via ``sys.modules`` so the tests run on any machine including
headless CI environments.


Package layout
--------------

.. code-block:: text

    big-tempo/
    ├── src/
    │   └── big_tempo/
    │       ├── __init__.py       version + headless-safe public exports
    │       ├── __main__.py       python -m big_tempo entry point
    │       ├── constants.py      visual / layout constants
    │       ├── config.py         defaults, loader, validator, BPM math helpers
    │       ├── cli.py            argument parser
    │       ├── midi.py           MidiHandler (mididings wrapper)
    │       ├── osc.py            OscSender – lazy (host, port) pool
    │       ├── tempo_list.py     TempoList (cyclic tempo store)
    │       └── app.py            BigTempo tkinter application
    ├── tests/
    │   ├── test_config.py        config loading, merging & validation
    │   ├── test_bpm_math.py      clamp / CC value mapping
    │   ├── test_midi_handler.py  MIDI routing & send_with_context
    │   ├── test_osc.py           OscSender pool (mocked)
    │   ├── test_transport.py     transport send dispatch & rolling token
    │   ├── test_config_reload.py hot-reload logic
    │   ├── test_quantize.py      BPM quantization
    │   └── test_tempo_list.py    TempoList cyclic logic
    ├── examples/
    │   └── example_config.py     annotated starter config
    ├── pyproject.toml
    └── README.rst
