"""Stage 1: extract the parts of a sim a reel needs into extract.json."""
import re
from datetime import timedelta

from .config import stable_hash
from .sim import Sim

EXTRACT_VERSION = 1
PERSONA_FIELDS = ("name", "first_name", "last_name", "age", "innate", "learned",
                  "currently", "lifestyle", "living_area", "daily_plan_req")
JUNK_DESCRIPTIONS = ("this is blank",)


def parse_description(desc):
  """Split a movement description "act (sub act) @ address" into parts.

  Chats look like "conversing about ... @ <persona> Other Name"."""
  desc = desc or ""
  act, _, address = desc.rpartition(" @ ")
  if not act:
    act, address = desc, ""
  m = re.match(r"^(.*?) \((.*)\)$", act)
  main, sub = (m.group(1), m.group(2)) if m else (act, None)
  chat_with = address[len("<persona> "):] if address.startswith("<persona> ") else None
  return {"act": main, "sub_act": sub, "address": address, "chat_with": chat_with}


def resolve_segment(sim, seg, focal_nodes):
  steps = sim.steps
  if "steps" in seg:
    s0, s1 = seg["steps"]
  else:
    missing = [n for n in seg["nodes"] if n not in focal_nodes]
    if missing:
      raise KeyError(f"segment {seg['name']}: unknown nodes {missing}")
    node_steps = [sim.step_at(focal_nodes[n]["created_dt"]) for n in seg["nodes"]]
    pad = seg.get("pad_steps", 0)
    s0, s1 = min(node_steps) - pad, max(node_steps) + pad
  s0, s1 = max(s0, steps[0]), min(s1, steps[-1])
  if s0 >= s1:
    raise ValueError(f"segment {seg['name']}: empty step range {s0}..{s1}")
  return s0, s1


def _collapse_activities(focal_labels, step1):
  acts = []
  for i, (step, _pron, desc) in enumerate(focal_labels):
    end = focal_labels[i + 1][0] - 1 if i + 1 < len(focal_labels) else step1
    acts.append({"start_step": step, "end_step": end, "description": desc,
                 **parse_description(desc)})
  return acts


def _conversations(states, focal, focal_nodes):
  """Dedupe chats found in movement state into conversations."""
  convs = {}
  for step, personas in states:
    for name, st in personas.items():
      chat = st.get("chat")
      if not chat:
        continue
      key = stable_hash(chat)
      c = convs.get(key)
      if c is None:
        speakers = []
        for spk, _ in chat:
          if spk not in speakers:
            speakers.append(spk)
        c = convs[key] = {
          "id": f"conv_{step}_{key[:6]}",
          "start_step": step,
          "end_step": step,
          "participants": speakers,
          "topic": parse_description(st.get("description"))["act"],
          "lines": [{"speaker": spk, "text": text} for spk, text in chat],
        }
      c["end_step"] = max(c["end_step"], step)
      c["start_step"] = min(c["start_step"], step)
      if name not in c["participants"]:
        c["participants"].append(name)
  out = sorted(convs.values(), key=lambda c: c["start_step"])
  for c in out:
    c["involves_focal"] = focal in c["participants"]
    lines = [[ln["speaker"], ln["text"]] for ln in c["lines"]]
    c["chat_nodes"] = sorted(
      (nid for nid, n in focal_nodes.items() if n["type"] == "chat" and n.get("filling") == lines),
      key=lambda nid: focal_nodes[nid]["node_count"])
  return out


def _memories(sim, nodes, t0, t1):
  out = []
  for nid, n in nodes.items():
    if not (t0 <= n["created_dt"] <= t1):
      continue
    if any(j in n["description"] for j in JUNK_DESCRIPTIONS):
      continue
    filling = n.get("filling") or []
    out.append({
      "id": nid,
      "type": n["type"],
      "created": n["created"],
      "step": sim.step_at(n["created_dt"]),
      "poignancy": n["poignancy"],
      "depth": n.get("depth", 0),
      "subject": n["subject"],
      "predicate": n["predicate"],
      "object": n["object"],
      "description": n["description"],
      # Thought nodes cite evidence node ids; chat nodes hold conversation lines.
      "evidence": filling if n["type"] == "thought" else [],
    })
  out.sort(key=lambda m: (m["created"], m["id"]))
  return out


def extract(cfg, sim=None):
  sim = sim or Sim(cfg["sim"])
  focal = cfg["persona"]
  if focal not in sim.persona_names:
    raise KeyError(f"persona '{focal}' not in sim {sim.code}")
  focal_nodes = sim.nodes(focal)
  lookback = cfg["beats"]["lookback_steps"]

  segments = []
  for seg in cfg["segments"]:
    s0, s1 = resolve_segment(sim, seg, focal_nodes)
    states = list(sim.states(s0, s1))
    clock = [sim.time_at(s).isoformat() for s, _ in states]
    tracks = {}
    for step, personas in states:
      for name, st in personas.items():
        tr = tracks.setdefault(name, {"xy": [], "labels": []})
        tr["xy"].append(list(st["movement"]))
        desc = st.get("description")
        if not tr["labels"] or tr["labels"][-1][2] != desc or tr["labels"][-1][1] != st.get("pronunciatio"):
          tr["labels"].append([step, st.get("pronunciatio"), desc])
    missing = [n for n, tr in tracks.items() if len(tr["xy"]) != len(states)]
    if missing:
      raise ValueError(f"segment {seg['name']}: personas missing from some steps: {missing}")
    t0 = sim.time_at(s0) - timedelta(seconds=lookback * sim.sec_per_step)
    segments.append({
      "name": seg["name"],
      "step0": s0,
      "step1": s1,
      "clock": clock,
      "tracks": tracks,
      "activities": _collapse_activities(tracks[focal]["labels"], s1),
      "conversations": _conversations(states, focal, focal_nodes),
      "memories": _memories(sim, focal_nodes, t0, sim.time_at(s1)),
    })

  scratch = sim.scratch(focal)
  return {
    "version": EXTRACT_VERSION,
    "config_hash": stable_hash({k: cfg[k] for k in ("sim", "persona", "segments")}),
    "sim": sim.code,
    "compressed": sim.compressed,
    "maze": sim.maze_name,
    "sec_per_step": sim.sec_per_step,
    "persona": focal,
    "persona_info": {k: scratch.get(k) for k in PERSONA_FIELDS},
    "personas": sorted(segments[0]["tracks"]),
    "segments": segments,
  }
