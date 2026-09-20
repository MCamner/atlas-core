"""Private CLI worker used only under the parent process deadline.

Directly invoking this module bypasses the parent guard; it is not a supported
public command or an isolation boundary on its own.
"""
from __future__ import annotations

import sys
from .cli import main

if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
