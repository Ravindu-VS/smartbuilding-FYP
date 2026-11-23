"""Host-side syntax / core-API check of the ESP32 firmware (firmware/tools/check_firmware.py).

Runs g++ -fsyntax-only on the sketch with stub headers for Arduino-ESP32 core 2.x and 3.x.
It is not an ESP32 compile. Skipped when g++ is missing."""
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_firmware_passes_syntax_and_core_api_check():
    compiler = os.environ.get("CXX", "g++")
    if shutil.which(compiler) is None:
        pytest.skip(f"{compiler} not installed")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "firmware", "tools", "check_firmware.py")],
                       capture_output=True, text=True, timeout=600)
    if r.returncode == 2:
        pytest.skip(r.stdout.strip())
    assert r.returncode == 0, r.stdout[-3000:]
    assert r.stdout.count("OK   ") == 2
