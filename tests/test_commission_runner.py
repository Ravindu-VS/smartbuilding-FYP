"""Offline parts of scripts/commission_room101.py (the hardware steps need the real board and Pi)."""
import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import commission_room101 as cr  # noqa: E402


def test_every_matrix_row_has_a_runner_test():
    ids = [t for t, _ in cr.TESTS]
    assert len(ids) == len(set(ids)) == 24
    assert {f"T{n:02d}" for n in range(1, 25)} == set(ids)


def test_room_state_is_found_wherever_it_is_nested():
    state = {"floors": [{"rooms": [{"room_id": "x", "sensors": {}}, {"room_id": cr.ROOM, "sensors": {"Light": 4.0}}]}]}
    assert cr.find_room(state)["sensors"]["Light"] == 4.0
    assert cr.find_room({"rooms": []}) is None


def test_evidence_files_keep_matrix_order_and_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "ROOT", str(tmp_path))
    run = cr.Run(types.SimpleNamespace(pi="10.0.0.2", port="COM8"))
    run.record("T16", cr.FAIL, "RED NO")
    run.record("T01", cr.PASS, "board running x")
    run.record("T07", cr.BLOCKED, "no 12 V branch")
    md = run.write()
    data = json.load(open(md[:-3] + ".json", encoding="utf-8"))
    assert [r["id"] for r in data["results"]] == ["T01", "T16", "T07"]
    text = open(md, encoding="utf-8").read()
    assert "Totals: PASS 1, FAIL 1, BLOCKED 1, NOT TESTED 0" in text


def test_operator_questions_never_default_to_yes(monkeypatch):
    answers = iter(["", "maybe", "n"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    assert cr.Asker().yes("Is the LED red?") is False


def test_list_option(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["commission_room101.py", "--list"])
    assert cr.main() == 0
    assert "T22  BLE telemetry fallback" in capsys.readouterr().out
