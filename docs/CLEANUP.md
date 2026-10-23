# Repository clean-up (23 Oct 2026)

Procedure followed: inventory -> references -> tracked vs generated -> regenerability -> list with reasons ->
recoverable quarantine -> full test run -> keep. Nothing was permanently deleted, git history was not
rewritten, and no dataset, model artifact, firmware file or research output was removed.

## 1. Inventory and references

* Live system (what runs): `raspberry_pi/`, `twin/`, `dashboard/fyp-research-twin/`, `firmware/`, plus the
  new `ml/`, `rl/`, `scripts/`, `experiments/run.py`, `tests/`.
* Every Python import in the live system was listed (`grep -E "^(from|import) "` over the live
  directories). The only link to the first architecture was `integration/building_config.py` (the 26-room
  configuration); the dashboard and the 3D twin import none of it.

## 2. Moved (git mv, recoverable)

| From | To | Reason |
|---|---|---|
| `integration/building_config.py` | `twin/building_config.py` | still the single room definition; moved next to its users |
| `agents/ ai/ app/ auth/ control/ sim/ hardware/ edge_gateway/ k8s/ wso2/ memory/ integration/` | `archive/legacy_v1/` | first architecture, not imported by the live system (details in `archive/README.md`) |
| 22 top-level scripts (`train_*`, `compare_*`, `evaluate_*`, `occupancy_*`, `smart_building_*`, `main.py`, `export_model.py`, `generate_simulated_occupancy_data.py`, `test_*.py`) | `archive/legacy_v1/` | superseded by `ml/`, `rl/`, `tests/` |
| `Dockerfile`, `docker-compose.yml`, `run_docker.bat`, `config.yaml`, `room_config.json`, `requirements.txt`, `dataset_comparison.*` | `archive/legacy_v1/` | configuration of the first design (docker-compose starts the FastAPI app and a dashboard folder that no longer exists); replaced by `scripts/`, `requirements/` |
| `data/generator.py`, old `experiments/*.py`, `output/experiments/` (results A-C) | `archive/legacy_v1/` | old simulator and its results (kept as research evidence) |
| `docs/` architecture/deployment/synchronisation documents, `docs/knowledge/`, `docs/hardware_implementation_guide.md` | `archive/legacy_v1/docs/` | describe the first design; the hardware guide's pins no longer match the firmware |
| `raspberry_pi/requirements.txt` | `archive/legacy_v1/raspberry_pi_requirements.txt` | replaced by `requirements/edge.txt` |
| `twin/tests/` | `tests/` | one test suite |

`run_local.bat` was first moved too and then restored: it is the live Windows start-up script (the README and the
dashboard refer to it). The reference search had missed `.bat` names; it now installs `requirements\train.txt`.

## 3. Kept although untracked (generated or local, git-ignored)

`output/twin_cache/` (learning-week cache, regenerated on demand), `output/smart_building.db` and
`output/metrics/` (outputs of the first design), `output/edge_store.sqlite3` (the edge brain's store),
`models/*.pkl` (legacy models; `final_unified_occupancy_pipeline.pkl` is still loadable for comparison),
`data/raw/`, `data/processed/*.csv`, `data/synthetic/` (regenerable from scripts; checksums in the
manifest), `extract_pptx.py` (a local helper already listed in `.gitignore`), `dashboard-next/` (empty).
These were not deleted: some are user data, and all are either regenerable or harmless.

## 4. Verification after the move

`python3 -m pytest -q` -> 90 passed (all suites, including the edge brain and the end-to-end flow); the
dashboard type-check (`npx tsc --noEmit`) and lint (`npx eslint src`) were clean; the edge brain started and
served the state. To restore anything: `git mv archive/legacy_v1/<path> <path>` or check out commit `35a384b`.

## 5. Permanent removal

Not done. The archive is about 3 MB; permanent removal can be done later by the project owner
with `git rm -r archive/legacy_v1/<path>` once the final report no longer refers to it.
