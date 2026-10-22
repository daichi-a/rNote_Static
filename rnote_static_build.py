#!/usr/bin/env python3
"""Build a legacy rNote source tree without running PHP."""
from rnote_static.build import main

if __name__ == "__main__":
    raise SystemExit(main())
