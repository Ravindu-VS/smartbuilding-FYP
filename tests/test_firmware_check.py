"""Host-side syntax / library-API check of the ESP32 firmware (firmware/tools/check_firmware.py).

Runs g++ -fsyntax-only on the sketch with stub core headers and the real headers of the SCD4x (1.x and 0.x)
and INA226 (Tillaart, INA226Lib) libraries. It is not an ESP32 compile; it catches syntax errors and library
API mismatches. Skipped when g++ is missing or the headers cannot be downloaded and are not cached."""
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_firmware_passes_syntax_and_library_api_check():
    if shutil.which("g++") is None:
        pytest.skip("g++ not installed")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "firmware", "tools", "check_firmware.py")],
                       capture_output=True, text=True, timeout=600)
    if r.returncode == 2:
        pytest.skip(r.stdout.strip())
    assert r.returncode == 0, r.stdout[-3000:]
    assert r.stdout.count("OK ") == 18
