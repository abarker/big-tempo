"""
Allow running the package directly: ``python -m big_tempo``.
"""

import signal
import sys
import tkinter as tk

from big_tempo.app    import BigTempo
from big_tempo.cli    import parse_args
from big_tempo.config import load_config


def main() -> None:
    args = parse_args()
    cfg  = load_config(args.config)
    root = tk.Tk()
    app  = BigTempo(root, args, cfg)

    # Make Ctrl-C work.
    #
    # tkinter's mainloop() runs in C and does not regularly check Python's
    # signal handler, so KeyboardInterrupt is never raised while the loop is
    # idle.  Registering a SIGINT handler that schedules root.destroy() via
    # root.after() fixes this: the signal arrives asynchronously, the handler
    # runs in the OS signal context, and root.after(0, ...) posts a callback
    # that the tkinter event loop picks up at its next idle iteration.
    signal.signal(signal.SIGINT, lambda _sig, _frame: root.after(0, root.destroy))

    try:
        root.mainloop()
    except KeyboardInterrupt:
        # Fallback for platforms where the signal approach is insufficient.
        pass
    finally:
        if app.jack_client:
            try:
                app.jack_client.deactivate()
                app.jack_client.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
