#!/usr/bin/env python3
"""
check_ns8_smoke_test.py - CheckMK local check minimale per test pipeline NS8

Version: 1.0.0
"""

import socket
import sys
import time

VERSION = "1.0.0"
SERVICE = "NS8 Smoke Test"


def main() -> int:
    now = int(time.time())
    host = socket.gethostname()
    print(f"0 {SERVICE} - OK v{VERSION} host={host} ts={now} | ts={now}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
