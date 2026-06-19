#!/usr/bin/env python3
"""check_opkg_packages.py - CheckMK OPKG check (pyuci beta).

BLOCKED: NethSecurity 8.8 no longer provides 'opkg'.
This script remains only for name parity with the original.
The APK variant is check_apk_packages.py (beta).
"""

import sys

BETA = True
VERSION = "1.0.0b1"
SERVICE = "OPKG.Packages"

try:
    from euci import EUci
except ImportError:
    EUci = None


def main():
    print(f"2 {SERVICE} - opkg not available on NethSecurity 8.8; use APK.Packages instead [beta]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
