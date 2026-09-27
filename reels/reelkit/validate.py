"""Consistency checks across the stage files, plus a human/agent-readable report."""
import re
from collections import defaultdict
from itertools import pairwise

from .config import stable_hash

MAP_W, MAP_H = 140, 100
EPS = 1e-3


def validate(extract, beats=None, timeline=None):
  """Return a list of (level, message); level is 'error' or 'warning'."""
  issues = []
  err = lambda m: issues.append(("error", m))
  warn = lambda m: issues.append(("warning", m))
  focal = extract["persona"]

  for seg in extract["segments"]:
    n = seg["step1"] - seg["step0"] + 1
    if len(seg["clock"]) != n:
      err(f"{seg['name']}: clock has {len(seg['clock'])} entries, expected {n}")
    for name, tr in seg["tracks"].items():
      if len(tr["xy"]) != n:
        err(f"{seg['name']}: track {name} has {len(tr['xy'])} positions, expected {n}")
      for x, y in tr["xy"]:
        if not (0 <= x < MAP_W and 0 <= y < MAP_H):
          err(f"{seg['name']}: {name} at ({x},{y}) is off the map")
          break
    xy = seg["tracks"][focal]["xy"]
    jumps = [seg["step0"] + i for i in range(1, n) if abs(xy[i][0] - xy[i - 1][0]) + abs(xy[i][1] - xy[i - 1][1]) > 1]
    if jumps:
      warn(f"{seg['name']}: {focal} moves more than 1 tile in a step at steps {jumps[:10]}")
    if seg["clock"] != sorted(seg["clock"]):
      err(f"{seg['name']}: clock is not monotonic")

  if beats is None:
    return issues
  if beats.get("extract_hash") != stable_hash(extract):
    warn("beats.json was built from a different extract.json (re-run `beats`)")
  convs = {c["id"]: c for seg in extract["segments"] for c in seg["conversations"]}
  seen = set()
  for bt in beats["beats"]:
    if bt["id"] in seen:
      err(f"duplicate beat id {bt['id']}")
    seen.add(bt["id"])
    if bt["type"] == "conversation":
      src = convs.get(bt["conversation_id"])
      if src is None:
        err(f"{bt['id']}: unknown conversation {bt['conversation_id']}")
      elif [(ln["speaker"], ln["text"]) for ln in bt["lines"]] != [(ln["speaker"], ln["text"]) for ln in src["lines"]]:
        warn(f"{bt['id']}: conversation lines differ from the sim (hand-edited?)")
    elif not bt.get("text"):
      warn(f"{bt['id']}: monologue has no text yet (placeholder will be used)")

  if timeline is None:
    return issues
  if timeline.get("beats_hash") != stable_hash(beats):
    warn("timeline.json was built from a different beats.json (re-run `timeline`)")
  spans = timeline["spans"]
  if not spans or abs(spans[0]["t0"]) > EPS:
    err("timeline does not start at t=0")
  last_step = {}
  for a, b in pairwise(spans):
    if abs(a["t1"] - b["t0"]) > EPS:
      err(f"gap/overlap between spans at t={a['t1']}..{b['t0']}")
  for sp in spans:
    if sp["t1"] <= sp["t0"]:
      err(f"empty or negative span at t={sp['t0']}")
    if sp["s1"] < sp["s0"]:
      err(f"span at t={sp['t0']} runs backwards in sim steps")
    if sp["s0"] < last_step.get(sp["seg"], -1):
      err(f"segment {sp['seg']} steps go backwards at t={sp['t0']}")
    last_step[sp["seg"]] = sp["s1"]
  if abs(spans[-1]["t1"] - timeline["duration"]) > EPS:
    err("timeline duration does not match the last span")
  seg_bounds = {i: (s["t0"], s["t1"]) for i, s in enumerate(timeline["segments"])}
  by_seg = defaultdict(list)
  for sp in timeline["speech"]:
    lo, hi = seg_bounds[sp["seg"]]
    if sp["t0"] < lo - EPS or sp["t1"] > hi + EPS:
      err(f"speech {sp['id']} falls outside its segment")
    if any(not (sp["t0"] - EPS <= wt <= sp["t1"] + EPS) for _, wt in sp["words"]):
      err(f"speech {sp['id']} has word times outside the clip")
    if sp["placeholder"]:
      warn(f"speech {sp['id']} is a placeholder")
    by_seg[sp["seg"]].append(sp)
  for items in by_seg.values():
    items.sort(key=lambda s: s["t0"])
    for a, b in pairwise(items):
      if b["t0"] < a["t1"] - EPS:
        err(f"speech {a['id']} and {b['id']} overlap")
  return issues


def _syllables(word):
  return max(1, len(re.findall(r"[aeiouy]+", word.lower())))


def text_stats(text):
  words = re.findall(r"[A-Za-z']+", text)
  sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
  return {
    "words": len(words),
    "words_per_sentence": round(len(words) / max(len(sentences), 1), 1),
    # Rough difficulty proxy: share of words with 3+ syllables.
    "long_word_ratio": round(sum(_syllables(w) >= 3 for w in words) / max(len(words), 1), 2),
  }


def report(extract, beats, timeline):
  lines = [(f"reel: {extract['persona']} in {extract['sim']}   duration {timeline['duration']:.1f}s   "
            f"timing: {timeline['timing_source']}")]
  for i, seg in enumerate(timeline["segments"]):
    spans = [s for s in timeline["spans"] if s["seg"] == i]
    speech = [s for s in timeline["speech"] if s["seg"] == i]
    modes = defaultdict(float)
    for s in spans:
      modes[s["mode"]] += s["t1"] - s["t0"]
    talk = sum(s["t1"] - s["t0"] for s in speech)
    dur = seg["t1"] - seg["t0"]
    lines.append(f"\n[{seg['name']}] steps {seg['step0']}..{seg['step1']}  {dur:.1f}s  "
                 f"speech {talk:.1f}s ({100 * talk / max(dur, EPS):.0f}%)")
    lines.append("  modes: " + ", ".join(f"{m} {d:.1f}s" for m, d in sorted(modes.items())))
    elided = sum(s["s1"] - s["s0"] for s in spans if s["mode"] == "elide")
    if elided:
      lines.append(f"  elided {elided} idle steps")
  lines.append("\nbeats:")
  for bt in beats["beats"]:
    text = bt.get("text") or ""
    if bt["type"] == "conversation":
      text = " ".join(ln["text"] for ln in bt["lines"])
      head = f"  {bt['id']} conversation {bt['conversation_id']} ({len(bt['lines'])} lines)"
    else:
      head = f"  {bt['id']} monologue [{bt['trigger']}] step {bt['step']}"
    st = text_stats(text) if text else None
    lines.append(head + (f"  words={st['words']} w/sent={st['words_per_sentence']} long={st['long_word_ratio']}" if st else "  (no text)"))
  return "\n".join(lines)
