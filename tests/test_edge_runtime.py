"""The Raspberry Pi runtime must work with flask + numpy (+ paho-mqtt) only: no pandas, scikit-learn,
scipy, joblib or gymnasium.  Runs the edge brain in a subprocess where those imports fail."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CODE = r'''
import sys, importlib.abc
BLOCK = ("pandas", "sklearn", "scipy", "joblib", "gymnasium")
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCK:
            raise ImportError(f"{name} is not part of the edge runtime")
sys.meta_path.insert(0, Blocker())
sys.path.insert(0, ROOT)
import raspberry_pi.edge_brain as eb
b = eb.EdgeBrain(speed_factor=360, warmup=False, store_path=STORE)
for _ in range(3):
    b.tick(1.0)
st = b.get_current_state()
assert len(st["rooms"]) == 26
b.inject_hardware_data({"room_id": eb.HARDWARE_ROOM_ID, "source": "test_sender", "temperature": 26.0, "humidity": 60.0, "lux": 100.0})
from rl.ppo import Policy
from rl.policy import PPOController, N_OBS, N_ACT
Policy(N_OBS, N_ACT).save(STORE + ".policy.json")
PPOController.load(STORE + ".policy.json")
print("EDGE_OK", "pandas" in sys.modules, "sklearn" in sys.modules)
'''


def test_edge_runs_without_training_stack(tmp_path):
    store = str(tmp_path / "edge.sqlite3")
    code = CODE.replace("ROOT", repr(ROOT)).replace("STORE", repr(store))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=600, cwd=ROOT)
    assert "EDGE_OK False False" in r.stdout, r.stdout[-2000:] + r.stderr[-4000:]
