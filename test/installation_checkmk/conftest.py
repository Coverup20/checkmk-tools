"""Shared pytest setup for the checkmk Python installer package's tests.

The package (script-tools/full/installation/checkmk) uses plain relative
imports (from lib.common import ..., from steps import ...), so its own
directory is added to sys.path to let those imports resolve normally - no
stubbing needed, everything imported is pure stdlib.
"""

import sys
from pathlib import Path

import pytest

PACKAGE_DIR = (
    Path(__file__).resolve().parents[2]
    / "script-tools"
    / "full"
    / "installation"
    / "checkmk"
)

if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))


@pytest.fixture()
def remove_all_module():
    import steps.remove_all as module

    return module


@pytest.fixture()
def installer_module():
    import installer as module

    return module
