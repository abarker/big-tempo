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
``libmidishare`` / ALSA) that pip cannot install for you.  Install them
first via your system package manager, then install the Python wrappers
manually before running ``pip install -e .``::

    # Debian / Ubuntu
    sudo apt install python3-jack python3-mididings python3-tk

    # or install the Python packages by hand after the C libs are present
    pip install JACK-Client mididings

Then install the package itself in editable mode::

    pip install -e .

For development (adds pytest)::

    pip install -e ".[dev]"


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

Default location: ``~/.config/big-tempo/config.json``

.. code-block:: json

    {
        "midi": {
            "client_name": "big_tempo_midi",
            "channel": 1
        },
        "buttons": {
            "increment": 1.0,
            "repeat_delay_ms": 400,
            "repeat_ms": 80
        },
        "min_bpm": 20.0,
        "max_bpm": 300.0,
        "receive": {
            "CC20": {"action": "up",   "amount": 1.0},
            "CC21": {"action": "down", "amount": 1.0},
            "CC22": {"action": "set"}
        },
        "send": {
            "on_change": {"cc": 30, "channel": 1}
        }
    }

Receive actions
~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 10 40

   * - Action
     - Effect
   * - ``up``
     - Add ``amount`` BPM
   * - ``down``
     - Subtract ``amount`` BPM
   * - ``set``
     - Map incoming value 0–127 → min_bpm–max_bpm

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
    └── README.rst
