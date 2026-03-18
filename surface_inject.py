#!/usr/bin/env python3
"""
Surface Kernel ISO Injector - Main entry point.

Usage:
    python surface_inject.py                  # Interactive CLI
    python surface_inject.py --gui            # Launch GUI
    python surface_inject.py inject -d sp7 -i arch.iso   # Direct CLI
    python surface_inject.py --help           # Show help
"""

import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    # Check if --gui flag is present
    if "--gui" in sys.argv:
        sys.argv.remove("--gui")
        from gui.main_window import run_gui
        sys.exit(run_gui())
    else:
        from cli.app import main as cli_main
        sys.exit(cli_main())


if __name__ == "__main__":
    main()
