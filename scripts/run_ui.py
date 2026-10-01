#!/usr/bin/env python3
"""Launch the local web UI.

    pip install flask
    python scripts/run_ui.py

Then open the printed URL (default http://127.0.0.1:5000) in your browser.
Everything runs locally on your machine — no data leaves your computer.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forexbot.logging_setup import setup_logging


def main() -> int:
    setup_logging()
    p = argparse.ArgumentParser(description="Run the forex-bot web UI.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    try:
        from forexbot.web import create_app
    except ImportError as exc:
        sys.exit(f"{exc}\n\nInstall the UI dependency with:  pip install flask")

    app = create_app()
    print(f"\n  Forex Bot UI running →  http://{args.host}:{args.port}\n"
          f"  (Ctrl+C to stop)\n")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
