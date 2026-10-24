#!/usr/bin/env python3
"""
Host-side syntax and library-API check of the ESP32-S3 firmware (no ESP32 toolchain needed).

    python3 firmware/tools/check_firmware.py

What it does: generates the function prototypes the Arduino IDE would add, then runs
`g++ -std=gnu++17 -fsyntax-only` on the sketch with
  * stub headers for the Arduino-ESP32 core, Wi-Fi, HTTPClient, ArduinoJson, BME280 and ESP32Servo
    (`firmware/tools/stubs/`, with the signatures the firmware uses), and
  * the REAL headers of the libraries whose APIs differ between versions, downloaded from GitHub into
    `firmware/tools/.lib_cache/` (git-ignored): Sensirion I2C SCD4x 1.1.0 and 0.4.0, INA226 (Rob Tillaart)
    0.6.6, INA226Lib, BH1750 1.3.0, ld2410,
for every combination of {SCD4x new, old, absent} x {INA226 Tillaart, INA226Lib, absent} x {core 3.x, 2.x}.

What it does NOT do: compile for the ESP32-S3, link, or prove the board works. Compile and flash with the
Arduino IDE (docs/HARDWARE.md, "Bring-up").
"""
import itertools
import os
import re
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.join(os.path.dirname(HERE), "esp32_smart_building")
INO = os.environ.get("INO", os.path.join(FW, "esp32_smart_building.ino"))
CACHE = os.path.join(HERE, ".lib_cache")
LIBS = {   # dir -> (url, file name)
    "scd4x_1": ("Sensirion/arduino-i2c-scd4x/1.1.0/src/SensirionI2cScd4x.h", "SensirionI2cScd4x.h"),
    "scd4x_0": ("Sensirion/arduino-i2c-scd4x/0.4.0/src/SensirionI2CScd4x.h", "SensirionI2CScd4x.h"),
    "ina226_tillaart": ("RobTillaart/INA226/0.6.6/INA226.h", "INA226.h"),
    "ina226lib": ("peterus/INA226Lib/HEAD/src/INA226.h", "INA226.h"),
    "common": ("claws/BH1750/1.3.0/src/BH1750.h", "BH1750.h"),
    "common2": ("ncmreynolds/ld2410/HEAD/src/ld2410.h", "ld2410.h"),
}


def fetch():
    for d, (path, name) in LIBS.items():
        dst = os.path.join(CACHE, d, name)
        if os.path.exists(dst):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with urllib.request.urlopen("https://raw.githubusercontent.com/" + path, timeout=30) as r:
            data = r.read()
        with open(dst, "wb") as f:
            f.write(data)


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
    try:
        fetch()
    except Exception as e:   # noqa: BLE001
        print(f"BLOCKED: could not download the library headers ({e})")
        return 2
    cpp = generate()
    ok = True
    for scd, ina, core in itertools.product(["scd4x_1", "scd4x_0", None], ["ina226_tillaart", "ina226lib", None], [3, 2]):
        inc = ["-I", os.path.dirname(cpp)]
        for d in (scd, ina, "common", "common2"):
            if d:
                inc += ["-I", os.path.join(CACHE, d)]
        inc += ["-I", os.path.join(HERE, "stubs")]
        cmd = ["g++", "-std=gnu++17", "-fsyntax-only", "-Wall", "-Wno-unused-variable", "-Wno-unused-but-set-variable",
               f"-DCORE_MAJOR={core}", "-DARDUINO=10819", *inc, cpp]
        r = subprocess.run(cmd, capture_output=True, text=True)
        tag = f"SCD4x={scd or 'not installed'}, INA226={ina or 'not installed'}, core {core}.x"
        print(("OK   " if r.returncode == 0 else "FAIL ") + tag)
        if r.returncode:
            ok = False
            print("\n".join(l for l in r.stderr.splitlines() if "error" in l)[:3000])
    print("all combinations pass the syntax/API check (not an ESP32 compile)" if ok else "errors found")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
