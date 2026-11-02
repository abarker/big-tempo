"""
big_tempo.transport – the JACK transport state as big_tempo sees it.
"""

import jack


def is_rolling(state) -> bool:
    """True while the JACK transport rolls or is about to.

    JACK's Starting state means rolling as soon as every client is ready.
    The transport passes through it at every start, and (JACK2) for at
    least one cycle at every relocate made while rolling, even with no
    slow-sync client.  Counting it as stopped made such a relocate look
    like a stop and a start, firing both transport sends: on the rig,
    Sync and mute_quantized off and back on for every loop.
    """
    return state in (jack.ROLLING,
                     getattr(jack, "STARTING", jack.ROLLING),
                     getattr(jack, "NETSTARTING", jack.ROLLING))
