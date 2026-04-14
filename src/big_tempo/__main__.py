"""
Allow running the package directly: ``python -m big_tempo``.
"""

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
    try:
        root.mainloop()
    except KeyboardInterrupt:
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
