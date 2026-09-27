"""Build the small test sim in tests/fixtures/mini_sim from skip-morning-s-14.

Keeps 3 personas and two step ranges: 1795..1850 (Sam and Jennifer's breakfast
conversation) and 2150..2160 (a jump in the sim clock at step 2156).
Run from the repo root: uv run python reels/tests/make_fixture.py
"""
import json
import shutil
from pathlib import Path

SRC = Path("environment/frontend_server/storage/skip-morning-s-14")
DST = Path(__file__).parent / "fixtures" / "mini_sim"
PERSONAS = ["Sam Moore", "Jennifer Moore", "Isabella Rodriguez"]
STEPS = list(range(1795, 1851)) + list(range(2150, 2161))
NODE_CUTOFF = "2023-02-13 06:05:00"


def main():
  if DST.exists():
    shutil.rmtree(DST)
  (DST / "movement").mkdir(parents=True)
  (DST / "reverie").mkdir()
  meta = json.loads((SRC / "reverie/meta.json").read_text())
  meta["persona_names"] = PERSONAS
  (DST / "reverie/meta.json").write_text(json.dumps(meta, indent=2))
  for s in STEPS:
    m = json.loads((SRC / f"movement/{s}.json").read_text())
    m["persona"] = {k: v for k, v in m["persona"].items() if k in PERSONAS}
    (DST / f"movement/{s}.json").write_text(json.dumps(m))
  src_p = SRC / "personas/Sam Moore/bootstrap_memory"
  dst_p = DST / "personas/Sam Moore/bootstrap_memory"
  (dst_p / "associative_memory").mkdir(parents=True)
  shutil.copy(src_p / "scratch.json", dst_p / "scratch.json")
  nodes = json.loads((src_p / "associative_memory/nodes.json").read_text())
  nodes = {k: v for k, v in nodes.items() if v["created"] <= NODE_CUTOFF}
  (dst_p / "associative_memory/nodes.json").write_text(json.dumps(nodes, indent=1))
  print(f"wrote {DST}")


if __name__ == "__main__":
  main()
