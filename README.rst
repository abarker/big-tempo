big-tempo
=========

A minimalist JACK tempo display with MIDI control via **mididings**.

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
  - Send CC on every user-initiated change

- Adopts JACK tempo changes from an external master (e.g. Hydrogen)
  without firing outgoing MIDI


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

Both ``jack`` and ``mididings`` are **optional** – the app starts without
them (JACK polling and MIDI are silently disabled).


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

Then install the package in editable mode::

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

    big-tempo                          # uses ~/.config/big-tempo/config.json
    big-tempo --config my_config.json
    big-tempo --no-titlebar --always-on-top
    python -m big_tempo                # also works

All CLI options::

    --config PATH         JSON config file
    --width-in FLOAT      Window width in inches
    --height-in FLOAT     Window height in inches
    --update-ms INT       JACK poll interval in milliseconds
    --font-size INT        Fixed font size in points (overrides auto-fit)
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

.. code-block:: python

    # big-tempo configuration
    {
        "midi": {
            "client_name": "big_tempo_midi",
            "channel": 1,
        },
        "buttons": {
            "increment": 1.0,           # BPM per click or repeat tick
            "repeat_delay_ms": 400,     # ms before hold-repeat starts
            "repeat_ms": 80,            # ms between repeat ticks
        },
        "min_bpm": 20.0,
        "max_bpm": 300.0,
        "receive": {
            "CC20": {"action": "up",   "amount": 1.0},
            "CC21": {"action": "down", "amount": 1.0},
            "CC22": {"action": "set"},  # maps 0-127 → min_bpm-max_bpm
        },
        "send": {
            "on_change": {"cc": 30, "channel": 1},
        },
    }

A fully annotated starter file is provided as ``example_config.py`` in the
repository root.  Copy it to the default location::

    mkdir -p ~/.config/big-tempo
    cp example_config.py ~/.config/big-tempo/config.py


Receive actions
~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 15 50

   * - Action
     - Effect
   * - ``up``
     - Add ``amount`` BPM
   * - ``down``
     - Subtract ``amount`` BPM
   * - ``set``
     - Map incoming CC value 0–127 → min_bpm–max_bpm
   * - ``list_append``
     - Save the current BPM to the end of the tempo list
   * - ``list_next``
     - Advance the tempo-list pointer by one step (wrapping cyclically),
       apply that BPM, and send the outgoing CC
   * - ``list_clear``
     - Discard all saved tempos and reset the list pointer

Tempo list
~~~~~~~~~~

The tempo list lets you pre-save a set of BPM values and recall them live
in order.  A typical workflow::

    # Soundcheck: dial in each song's tempo, then:
    CC23  →  list_append   (repeat for each song)

    # Performance: one stomp per song to change tempo
    CC24  →  list_next     (cycles back to start after the last entry)

    # End of night
    CC25  →  list_clear

Send
~~~~

``send.on_change`` fires the current BPM (mapped to 0–127) on the
configured CC number whenever the user changes BPM via the buttons or
incoming MIDI.  JACK-initiated tempo changes do **not** trigger a send.

Button hold-repeat
~~~~~~~~~~~~~~~~~~

Holding ▲ or ▼ fires one tick immediately, then waits ``repeat_delay_ms``
before entering a fast repeat loop at ``repeat_ms`` per tick.  Both
intervals are configurable per-config.


OSC output (Hydrogen absolute tempo)
-------------------------------------

Hydrogen's MIDI interface only exposes *relative* BPM commands
(``BPM_CC_RELATIVE``), which require knowing the receiver's current tempo to
compute the right delta – unreliable over async transport.

Hydrogen's OSC interface (``Edit → Preferences → OSC``, default port 9000)
accepts ``/Hydrogen/BPM <float>`` as an **absolute** tempo command, making it
the correct channel for deterministic tempo control.

Install the pure-Python OSC library::

    pip install python-osc

Then enable OSC in ``config.py``::

    "osc": {
        "host":      "127.0.0.1",   # Hydrogen host
        "port":      9000,           # Hydrogen OSC port (default 9000)
        "address":   "/Hydrogen/BPM",
        "on_change": True,           # was False
    },

Every user-initiated BPM change (buttons, incoming MIDI CC, or
``list_next``) will then fire both the outgoing MIDI CC **and** the OSC
message.  JACK-initiated changes still do not trigger either.

If ``python-osc`` is not installed, a one-time warning is printed to stderr
and the program continues with MIDI-only output.

MIDI relative workaround (not recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If OSC is unavailable, Hydrogen's ``BPM_CC_RELATIVE`` action interprets CC
values using the standard signed-encoder convention:

* Values **1–63**  → +1 to +63 BPM
* Values **65–127** → −63 to −1 BPM
* Value **0** → no change

Maximum single-message swing is ±63 BPM.  Reaching an arbitrary target
requires two hops for large jumps, and computing the right delta demands
certainty about Hydrogen's current tempo – which the async JACK poll cannot
guarantee.  OSC is strongly preferred.


Development
-----------

.. code-block:: bash

    # Run the full test suite (no JACK server or MIDI hardware required)
    pytest

    # With coverage report
    pytest --cov=big_tempo --cov-report=term-missing

The tests stub out ``jack`` and ``mididings`` via ``sys.modules`` so they
run on any machine, including headless CI environments.


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
    │       └── app.py            BigTempo tkinter application
    ├── tests/
    │   ├── test_config.py        config loading & merging
    │   ├── test_bpm_math.py      clamp / CC value mapping
    │   └── test_midi_handler.py  MIDI routing (mididings mocked)
    ├── pyproject.toml
    ├── README.rst
    └── example_config.py
