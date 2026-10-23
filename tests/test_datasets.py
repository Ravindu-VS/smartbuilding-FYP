"""Datasets: provenance manifest, checksums, raw/processed separation, reproducible preprocessing."""
import hashlib
import json
import os

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "data", "manifest.json")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def manifest():
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def test_manifest_documents_every_raw_dataset():
    m = manifest()
    assert set(m["provenance_classes"]) == {"public_real", "room101_measured", "synthetic", "prediction", "derived"}
    for name, d in m["raw"].items():
        for key in ("name", "publisher", "citation", "licence", "accessed", "download_source", "provenance", "files"):
            assert d.get(key), f"{name}: {key} missing"
        for fname, f in d["files"].items():
            assert f["url"].startswith("https://") and len(f["sha256"]) == 64


def test_tracked_uci_copy_matches_the_manifest():
    m = manifest()["raw"]["uci_occupancy"]["files"]
    for fname, f in m.items():
        p = os.path.join(ROOT, "Dataset", "UCI", "occupancy+detection", fname)
        assert sha(p) == f["sha256"]
        k = os.path.join(ROOT, "Dataset", "Kaggle_Room_Occupancy", fname)
        assert sha(k) == f["sha256"]            # the "Kaggle" files are the same UCI files


def test_processed_uci_table_is_ordered_and_complete():
    p = os.path.join(ROOT, "data", "processed", "uci_occupancy.csv")
    if not os.path.exists(p):
        pytest.skip("run scripts/preprocess_datasets.py")
    df = pd.read_csv(p, parse_dates=["timestamp"])
    assert len(df) == 20560 and df.timestamp.is_monotonic_increasing and not df.timestamp.duplicated().any()
    assert set(df.provenance) == {"public_real"}
    spans = df.groupby("source_file").timestamp.agg(["min", "max"]).sort_values("min")
    assert (spans["min"].values[1:] > spans["max"].values[:-1]).all()        # files do not overlap in time


def test_preprocessing_is_reproducible():
    m = manifest()
    p = os.path.join(ROOT, "data", "processed", "uci_occupancy.csv")
    if not os.path.exists(p):
        pytest.skip("run scripts/preprocess_datasets.py")
    assert sha(p) == m["processed"]["uci_occupancy.csv"]["sha256"]
    b = os.path.join(ROOT, "data", "processed", "bdg2_panther_office.csv")
    if os.path.exists(b):
        assert sha(b) == m["processed"]["bdg2_panther_office.csv"]["sha256"]


def test_raw_downloads_are_not_committed():
    gi = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    for pat in ("data/raw/uci_occupancy/", "data/raw/bdg2/", "data/processed/*.csv", "data/synthetic/"):
        assert pat in gi
