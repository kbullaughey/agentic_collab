"""Reel configuration loading and repo paths."""
import copy
import hashlib
import json
from pathlib import Path

import yaml

REELS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = REELS_ROOT.parent
FRONTEND = REPO_ROOT / "environment" / "frontend_server"
STORAGE = FRONTEND / "storage"
COMPRESSED_STORAGE = FRONTEND / "compressed_storage"
ASSETS = FRONTEND / "static_dirs" / "assets"
PROMPTS = REELS_ROOT / "prompts"
VIEWER = REELS_ROOT / "viewer"
OUT = REELS_ROOT / "out"

DEFAULTS = {
  "sim": None,
  "persona": None,
  "segments": [],
  "prompts": {"monologue": "monologue/v1", "model": None},
  "beats": {
    # Minimum sim steps between two monologue beats.
    "min_gap_steps": 30,
    # How far back (in steps) to look for memories when building context.
    "lookback_steps": 90,
    "max_memories": 8,
    # Radius in tiles for "nearby" personas.
    "nearby_tiles": 6,
  },
  "pacing": {
    "chars_per_min": 750,
    # Sim steps per reel second when nothing special is happening.
    "base_steps_per_s": 2.0,
    "walk_speedup": 4.0,
    "max_idle_s": 1.5,
    "min_gap_s": 0.4,
    "lead_in_s": 0.3,
    "fade_s": 1.0,
    # Runs of moving/idle steps shorter than this are merged with neighbors.
    "min_run_steps": 3,
  },
  "camera": {"edge_margin_tiles": 6, "zoom": 1.0, "pan_ms": 600},
  # Speaker -> Inworld voice id; "_monologue" optionally overrides the focal
  # persona's voice for inner monologue.
  "voices": {},
  "tts": {
    "model": "inworld-tts-2",
    "speaking_rate": None,
    "language": "en-US",
    # Set to print a cost estimate in `reel.py tts --dry-run`.
    "usd_per_million_chars": None,
  },
}


def _merge(base, override):
  out = copy.deepcopy(base)
  for k, v in (override or {}).items():
    if isinstance(v, dict) and isinstance(out.get(k), dict):
      out[k] = _merge(out[k], v)
    else:
      out[k] = v
  return out


def load_config(path):
  path = Path(path)
  with open(path) as f:
    raw = yaml.safe_load(f) or {}
  cfg = _merge(DEFAULTS, raw)
  for key in ("sim", "persona"):
    if not cfg[key]:
      raise ValueError(f"{path}: '{key}' is required")
  if not cfg["segments"]:
    raise ValueError(f"{path}: at least one segment is required")
  for i, seg in enumerate(cfg["segments"]):
    seg.setdefault("name", f"seg{i}")
    if ("steps" in seg) == ("nodes" in seg):
      raise ValueError(f"{path}: segment {seg['name']} needs exactly one of 'steps' or 'nodes'")
  cfg["name"] = raw.get("name", path.stem)
  cfg["_path"] = str(path)
  return cfg


def out_dir(cfg):
  d = OUT / cfg["name"]
  d.mkdir(parents=True, exist_ok=True)
  return d


def stable_hash(obj):
  data = json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()
  return hashlib.sha256(data).hexdigest()[:16]


def write_json(path, obj):
  path = Path(path)
  tmp = path.with_suffix(path.suffix + ".tmp")
  with open(tmp, "w") as f:
    json.dump(obj, f, indent=1, ensure_ascii=False)
  tmp.replace(path)


def read_json(path):
  with open(path) as f:
    return json.load(f)
