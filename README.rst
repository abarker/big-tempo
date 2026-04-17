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
  - Send CC on every user-initiated change, with configurable value encoding

- **python-osc OSC output** for absolute tempo commands (recommended for
  Hydrogen, which only supports relative BPM over MIDI)
- **Tempo list** – save BPM snapshots during soundcheck and cycle through
  them live via a single footswitch
- Per-receive OSC and MIDI sends – any incoming CC can trigger additional
  output messages independently of its BPM action
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
     - ``pip install python-osc`` (pure Python, no C extensions required)

``jack``, ``mididings``, and ``python-osc`` are all **optional** – the app
starts without any of them (each feature degrades gracefully with a one-time
warning to stderr).


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

Then install the package and the OSC library::

    pip install -e .
    pip install python-osc

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


Config file
-----------

Default location: ``~/.config/big-tempo/config.py``

The file must contain a single Python **dict literal**.  Full ``#`` comment
syntax and trailing commas are supported (unlike JSON).  It is parsed with
``ast.literal_eval`` – no arbitrary code is executed.

A fully annotated starter file is provided as ``example_config.py`` in the
repository root::

    mkdir -p ~/.config/big-tempo
    cp example_config.py ~/.config/big-tempo/config.py

.. code-block:: python

    {
        "midi":    {"client_name": "big_tempo_midi", "channel": 1},
        "buttons": {"increment": 1.0, "repeat_delay_ms": 400, "repeat_ms": 80},
        "min_bpm": 20.0,
        "max_bpm": 300.0,
        "receive":   { ... },   # see Receive actions below
        "midi_send": { ... },   # outgoing MIDI CC
        "osc":       { ... },   # OSC connection info
        "osc_send":  { ... },   # outgoing OSC messages
    }


Receive actions
~~~~~~~~~~~~~~~

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
       and fire outgoing MIDI + OSC
   * - ``list_clear``
     - Discard all saved tempos and reset the list pointer
   * - ``osc_only``
     - Fire the entry's ``osc_send`` without changing tempo
   * - ``midi_only``
     - Fire the entry's ``midi_send`` without changing tempo

Any receive entry may carry both an ``osc_send`` and/or ``midi_send`` key to
fire extra messages alongside its primary action::

    "receive": {
        # BPM up + log over OSC
        "CC20": {"action": "up", "amount": 1.0,
                 "osc_send": {"address": "/log/up", "args": ["bpm", "raw"]}},

        # Trigger Hydrogen PLAY – no BPM change
        "CC26": {"action": "osc_only",
                 "osc_send": {"address": "/Hydrogen/PLAY", "args": []}},

        # Fire a fixed CC to a DAW – no BPM change
        "CC27": {"action": "midi_only",
                 "midi_send": {"cc": 50, "channel": 2, "value": 127}},
    },


MIDI send (``midi_send``)
~~~~~~~~~~~~~~~~~~~~~~~~~

Fires a MIDI CC on user-initiated BPM changes (buttons, incoming MIDI,
``list_next``).  JACK-initiated changes do **not** trigger a send.

The ``"value"`` field is **required** in every ``midi_send`` spec.  Omitting
it prints a one-time warning to stderr and skips that send entirely.

.. list-table::
   :header-rows: 1
   :widths: 15 45

   * - Token
     - Result
   * - ``"bpm"``
     - Current BPM mapped proportionally to 0–127
   * - ``"raw"``
     - Incoming CC value passed straight through (0–127)
   * - ``"rolling"``
     - 127 on transport start, 0 on transport stop
   * - ``<int 0–127>``
     - Fixed literal value

::

    "midi_send": {
        "on_change": {"cc": 30, "channel": 1, "value": "bpm"},
        # "on_change": {"cc": 31, "channel": 1, "value": 64},    # always 64
    },


OSC output (``osc`` + ``osc_send``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Recommended for controlling **Hydrogen's tempo absolutely**.  Hydrogen's
MIDI interface only supports relative BPM changes (``BPM_CC_RELATIVE``,
±63 BPM max, error-prone over async transport).  Its OSC interface accepts
``/Hydrogen/BPM <float>`` as an absolute command.

Enable OSC in Hydrogen: ``Edit → Preferences → OSC`` (default port 9000).

Install the library::

    pip install python-osc

Config::

    "osc": {
        "host": "127.0.0.1",
        "port": 9000,
    },
    "osc_send": {
        "on_change": {"address": "/Hydrogen/BPM", "args": ["bpm"]},
    },

``"args"`` tokens (same convention as per-receive ``osc_send``):

.. list-table::
   :header-rows: 1
   :widths: 15 45

   * - Token
     - Result
   * - ``"bpm"``
     - Current BPM as a float
   * - ``"raw"``
     - Incoming CC value 0–127 as an int
   * - ``<literal>``
     - Passed through unchanged (int, float, str, bool)


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
    │       ├── config.py         defaults, loader, BPM math helpers
    │       ├── cli.py            argument parser
    │       ├── midi.py           MidiHandler (mididings wrapper)
    │       ├── osc.py            OscSender (python-osc wrapper)
    │       ├── tempo_list.py     TempoList (cyclic tempo store)
    │       └── app.py            BigTempo tkinter application
    ├── tests/
    │   ├── test_config.py        config loading & merging
    │   ├── test_bpm_math.py      clamp / CC value mapping
    │   ├── test_midi_handler.py  MIDI routing & send_with_context
    │   ├── test_osc.py           OscSender (mocked)
    │   └── test_tempo_list.py    TempoList cyclic logic
    ├── pyproject.toml
    ├── README.rst
    └── example_config.py
