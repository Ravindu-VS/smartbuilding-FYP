#!/usr/bin/env python3
"""
Host-side syntax and library-API check of the ESP32-S3 firmware (no ESP32 toolchain needed).

    python3 firmware/tools/check_firmware.py

What it does: generates the function prototypes the Arduino IDE would add, then runs
`g++ -std=gnu++17 -fsyntax-only` on the sketch with stub headers in `firmware/tools/stubs/`
for both Arduino-ESP32 core 2.x and 3.x.

What it does NOT do: compile for the ESP32-S3, link, or prove the board works. Compile and flash with the
Arduino IDE (docs/HARDWARE.md, "Bring-up").
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.join(os.path.dirname(HERE), "esp32_smart_building")
INO = os.environ.get("INO", os.path.join(FW, "esp32_smart_building.ino"))
CACHE = os.path.join(HERE, ".lib_cache")


def generate() -> str:
    src = open(INO, encoding="utf-8").read()
    types = r"(?:void|bool|float|int|double|String|uint8_t|uint16_t|int16_t|uint32_t|long|unsigned long|const char\*)"
    pat = re.compile(rf"^({types})\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*\{{", re.M)
    protos = [f"{m.group(1)} {m.group(2)}({re.sub(r'=[^,]*', '', m.group(3))});" for m in pat.finditer(src)]
    first = pat.search(src).start()
    out = os.path.join(CACHE, "gen")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "fw.cpp"), "w", encoding="utf-8") as f:
        f.write(src[:first] + "\n// generated prototypes\n" + "\n".join(protos) + "\n" + src[first:])
    with open(os.path.join(FW, "secrets.example.h"), encoding="utf-8") as f, \
            open(os.path.join(out, "secrets.h"), "w", encoding="utf-8") as g:
        g.write(f.read())          # never the real secrets.h
    return os.path.join(out, "fw.cpp")


def main() -> int:
    compiler = os.environ.get("CXX", "g++")
    if shutil.which(compiler) is None:
        print(f"BLOCKED: {compiler} not found")
        return 2
    cpp = generate()
    ok = True
    for core in (3, 2):
        inc = ["-I", os.path.dirname(cpp), "-I", os.path.join(HERE, "stubs")]
        cmd = [compiler, "-std=gnu++17", "-fsyntax-only", "-Wall", "-Wno-unused-variable", "-Wno-unused-but-set-variable",
               f"-DCORE_MAJOR={core}", "-DARDUINO=10819", *inc, cpp]
        r = subprocess.run(cmd, capture_output=True, text=True)
        tag = f"Arduino-ESP32 core {core}.x"
        print(("OK   " if r.returncode == 0 else "FAIL ") + tag)
        if r.returncode:
            ok = False
            print("\n".join(l for l in r.stderr.splitlines() if "error" in l)[:3000])
    print("both core-stub syntax checks pass (not an ESP32 compile)" if ok else "errors found")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
