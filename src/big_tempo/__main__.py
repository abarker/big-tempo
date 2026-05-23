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

    # Validate an explicitly supplied --config path before trying to load it.
    # The default path (~/.config/big-tempo/config.py) may legitimately not
    # exist (new install), so that case is handled silently inside load_config.
    if args.config is not None:
        import os as _os
        if not _os.path.exists(args.config):
            print(f"Error: config file not found: {args.config}", file=sys.stderr)
            sys.exit(1)
        if not _os.path.isfile(args.config):
            print(f"Error: config path is not a file: {args.config}", file=sys.stderr)
            sys.exit(1)

    # strict=True: a parse error in an explicitly supplied file is fatal rather
    # than silently falling back to defaults (which would be very confusing).
    cfg = load_config(args.config, strict=args.config is not None)
    root = tk.Tk()
    app  = BigTempo(root, args, cfg)

    # Make Ctrl-C and SIGTERM work cleanly.
    #
    # tkinter's mainloop() runs in C and does not regularly check Python's
    # signal handler, so KeyboardInterrupt is never raised while the loop is
    # idle.  Registering handlers that schedule app._on_close() via root.after()
    # fixes this: the signal arrives asynchronously, the handler runs in the OS
    # signal context, and root.after(0, ...) posts a callback that the tkinter
    # event loop picks up at its next idle iteration.
    #
    # Routing through app._on_close (rather than root.destroy directly) ensures
    # the window position is saved even when the process is terminated by a signal.
    _close = lambda _sig, _frame: root.after(0, app._on_close)
    signal.signal(signal.SIGINT,  _close)
    signal.signal(signal.SIGTERM, _close)

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
