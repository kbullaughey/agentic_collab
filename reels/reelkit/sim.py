"""Read saved simulations (uncompressed storage or compressed_storage).

Uncompressed sims (storage/<sim>/movement/<step>.json) carry the real clock
time of every step, which matters because the sim clock is not linear. A
compressed sim (compressed_storage/<sim>/master_movement.json) only stores
changes, and its clock is reconstructed as start_date + step * sec_per_step.
"""
import bisect
import json
import sys
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path

from .config import COMPRESSED_STORAGE, STORAGE

TIME_FMT = "%B %d, %Y, %H:%M:%S"
NODE_TIME_FMT = "%Y-%m-%d %H:%M:%S"


def parse_sim_time(s):
  return datetime.strptime(s, TIME_FMT)


def parse_node_time(s):
  return datetime.strptime(s, NODE_TIME_FMT)


def resolve_sim(sim):
  """Return the directory of a sim given a code or a path."""
  p = Path(sim)
  if p.is_dir():
    return p
  for base in (STORAGE, COMPRESSED_STORAGE):
    if (base / sim).is_dir():
      return base / sim
  raise FileNotFoundError(f"sim '{sim}' not found in {STORAGE} or {COMPRESSED_STORAGE}")


class Sim:
  def __init__(self, sim):
    self.root = resolve_sim(sim)
    self.code = self.root.name
    self.compressed = (self.root / "master_movement.json").exists()
    meta_path = self.root / ("meta.json" if self.compressed else "reverie/meta.json")
    with open(meta_path) as f:
      self.meta = json.load(f)
    self.sec_per_step = self.meta["sec_per_step"]
    self.maze_name = self.meta.get("maze_name", "the_ville")
    self._cache = {}
    if self.compressed:
      print(f"warning: {self.code} is compressed; assuming a linear clock "
            f"(start_date + step*{self.sec_per_step}s)", file=sys.stderr)

  # --- steps and clock -------------------------------------------------------

  @cached_property
  def _master(self):
    with open(self.root / "master_movement.json") as f:
      return {int(k): v for k, v in json.load(f).items()}

  @cached_property
  def steps(self):
    """Sorted list of steps that have movement data."""
    if self.compressed:
      return sorted(self._master)
    return sorted(int(p.stem) for p in (self.root / "movement").glob("*.json"))

  @cached_property
  def persona_names(self):
    return list(self.meta["persona_names"])

  def _movement_file(self, step):
    if step not in self._cache:
      with open(self.root / "movement" / f"{step}.json") as f:
        self._cache[step] = json.load(f)
    return self._cache[step]

  def time_at(self, step):
    if self.compressed:
      start = datetime.strptime(self.meta["start_date"], "%B %d, %Y")
      return start + timedelta(seconds=step * self.sec_per_step)
    return parse_sim_time(self._movement_file(step)["meta"]["curr_time"])

  @cached_property
  def clock(self):
    """(steps, times) for every available step, sorted."""
    return self.steps, [self.time_at(s) for s in self.steps]

  def step_at(self, when):
    """The last step whose clock time is <= `when` (clamped to the first step)."""
    steps, times = self.clock
    i = bisect.bisect_right(times, when) - 1
    return steps[max(i, 0)]

  # --- per-step persona state -----------------------------------------------

  def states(self, step0, step1):
    """Yield (step, {persona: {movement, pronunciatio, description, chat}}) for
    step0..step1 inclusive. Compressed sims are forward-filled."""
    if self.compressed:
      state = {}
      for s in range(step1 + 1):
        for name, delta in self._master.get(s, {}).items():
          state.setdefault(name, {}).update(delta)
        if s >= step0:
          yield s, {k: dict(v) for k, v in state.items()}
      return
    for s in range(step0, step1 + 1):
      if not (self.root / "movement" / f"{s}.json").exists():
        raise FileNotFoundError(f"{self.code}: missing movement/{s}.json")
      yield s, self._movement_file(s)["persona"]

  # --- persona memory -------------------------------------------------------

  def _persona_dir(self, persona):
    return self.root / "personas" / persona / "bootstrap_memory"

  def scratch(self, persona):
    with open(self._persona_dir(persona) / "scratch.json") as f:
      return json.load(f)

  def nodes(self, persona):
    """Memory nodes as a dict node_id -> node, with parsed `created_dt`."""
    with open(self._persona_dir(persona) / "associative_memory" / "nodes.json") as f:
      nodes = json.load(f)
    for n in nodes.values():
      n["created_dt"] = parse_node_time(n["created"])
    return nodes
