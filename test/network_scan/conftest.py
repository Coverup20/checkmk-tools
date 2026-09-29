"""Shared pytest setup for network_topology_map.py tests.

The script lives in the repo itself (script-tools/full/network_scan), not in
/usr/local/bin, and has no third-party dependencies (rendering shells out to
the `dot` binary) - so it's loaded directly via importlib from its actual
path, no stubbing needed for the pure-logic tests.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "script-tools"
    / "full"
    / "network_scan"
    / "network_topology_map.py"
)


@pytest.fixture()
def topology_module():
    spec = importlib.util.spec_from_file_location("network_topology_map", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules before exec: dataclasses resolves string
    # annotations (from __future__ import annotations) via
    # sys.modules[cls.__module__], which is None otherwise.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
