#!/usr/bin/env python3
"""
Download the public datasets used by the project into data/raw/ and verify them.

    python scripts/fetch_datasets.py            # download what is missing, verify all
    python scripts/fetch_datasets.py --verify   # verify only (no network)

Every file is checked against the SHA-256 recorded in data/manifest.json the first
time it was downloaded (23 Oct 2026).  A mismatch is reported, never ignored: the
upstream file has changed and the processed data and models would no longer be
reproducible from it.

Sources (see docs/DATASETS.md for licences and variables):
  uci_occupancy  UCI Occupancy Detection (Candanedo & Feldheim 2016), CC BY 4.0.
                 Downloaded from the dataset author's repository
                 github.com/LuisM78/Occupancy-detection-data; the UCI archive
                 (archive.ics.uci.edu, DOI 10.24432/C5X01N) was not reachable from the
                 development environment.  The same three files are also kept in
                 Dataset/UCI/occupancy+detection/ (byte-identical, same SHA-256).
  bdg2           Building Data Genome Project 2 (Miller et al. 2020), licence file in
                 the repository: "Attribution-ShareAlike 4.0" (CC BY-SA 4.0).
                 github.com/buds-lab/building-data-genome-project-2 (Git LFS files).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "data", "manifest.json")

UCI = "https://raw.githubusercontent.com/LuisM78/Occupancy-detection-data/master/"
BDG2 = "https://media.githubusercontent.com/media/buds-lab/building-data-genome-project-2/master/data/"

SOURCES = {
    "uci_occupancy": {
        "files": {
            "datatraining.txt": UCI + "datatraining.txt",
            "datatest.txt": UCI + "datatest.txt",
            "datatest2.txt": UCI + "datatest2.txt",
        },
        "mirror_dir": os.path.join(ROOT, "Dataset", "UCI", "occupancy+detection"),
    },
    "bdg2": {
        "files": {
            "metadata.csv": BDG2 + "metadata/metadata.csv",
            "weather.csv": BDG2 + "weather/weather.csv",
            "electricity_cleaned.csv": BDG2 + "meters/cleaned/electricity_cleaned.csv",
        },
    },
}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def download(url: str, dest: str) -> None:
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    os.replace(tmp, dest)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true", help="only verify files already present")
    ap.add_argument("--dataset", choices=sorted(SOURCES), action="append", help="limit to a dataset")
    args = ap.parse_args(argv)
    manifest = load_manifest()
    raw = manifest["raw"]
    failures = 0
    for name in args.dataset or sorted(SOURCES):
        src = SOURCES[name]
        out_dir = os.path.join(ROOT, "data", "raw", name)
        os.makedirs(out_dir, exist_ok=True)
        for fname, url in src["files"].items():
            dest = os.path.join(out_dir, fname)
            expected = raw[name]["files"][fname]["sha256"]
            if not os.path.exists(dest):
                mirror = os.path.join(src.get("mirror_dir", ""), fname)
                if src.get("mirror_dir") and os.path.exists(mirror) and sha256(mirror) == expected:
                    shutil.copyfile(mirror, dest)
                    print(f"[copy]     {name}/{fname} from {os.path.relpath(mirror, ROOT)}")
                elif args.verify:
                    print(f"[missing]  {name}/{fname}")
                    failures += 1
                    continue
                else:
                    print(f"[download] {name}/{fname} <- {url}")
                    try:
                        download(url, dest)
                    except Exception as e:      # report and continue with the other files
                        print(f"[error]    {name}/{fname}: {e}")
                        failures += 1
                        continue
            got = sha256(dest)
            if got != expected:
                print(f"[MISMATCH] {name}/{fname}: sha256 {got} != manifest {expected}")
                failures += 1
            else:
                print(f"[ok]       {name}/{fname} ({os.path.getsize(dest):,} bytes)")
    print("verified on", date.today().isoformat(), "-", "all files OK" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
