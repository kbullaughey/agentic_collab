"""Stage 2: split each segment into ordered beats (the reel script skeleton).

Beats are conversations the focal persona takes part in and monologue beats
placed at segment starts, activity changes, and right after conversations.
Each monologue beat stores its context and its fully rendered prompt so the
input to the LLM can be reviewed (and hand-edited in beats.json) before any
text is generated.
"""
import math
from datetime import datetime
from string import Template

from .config import PROMPTS, stable_hash
from .extract import parse_description

BEATS_VERSION = 1
MARKER = "<commentblockmarker>###</commentblockmarker>"
# Lower number wins when two monologue candidates are too close together.
TRIGGER_PRIORITY = {"after_conversation": 0, "segment_start": 1, "activity_change": 2}
TRIGGER_NOTES = {
  "segment_start": "the start of this scene; set the scene from the character's point of view",
  "activity_change": "the character is starting a new activity",
  "after_conversation": "the conversation above has just ended; the character reflects on it",
}


def load_prompt(name):
  path = PROMPTS / f"{name}.txt"
  text = path.read_text()
  if MARKER in text:
    text = text.split(MARKER, 1)[1]
  return text.strip() + "\n"


def render_prompt(template, fields):
  return Template(template).substitute(fields)


def humanize_address(address):
  """'the Ville:Moore family's house:main room:bed' -> 'bed, main room, Moore family's house'"""
  if not address:
    return "unknown"
  if address.startswith("<persona> "):
    return f"with {address[len('<persona> '):]}"
  parts = [p for p in address.split(":") if p and p != "the Ville"]
  return ", ".join(reversed(parts))


def humanize_time(iso):
  dt = datetime.fromisoformat(iso)
  return dt.strftime("%-I:%M %p on %A, %B %-d")


def activity_text(a):
  if a is None:
    return "nothing notable"
  if a.get("chat_with"):
    return f"talking with {a['chat_with']}"
  if a["sub_act"] and a["sub_act"] != a["act"]:
    return f"{a['act']} ({a['sub_act']})"
  return a["act"]


def _activity_at(seg, step):
  for a in seg["activities"]:
    if a["start_step"] <= step <= a["end_step"]:
      return a
  return None


def _nearby(seg, focal, step, radius):
  i = step - seg["step0"]
  fx, fy = seg["tracks"][focal]["xy"][i]
  out = []
  for name, tr in seg["tracks"].items():
    if name == focal:
      continue
    x, y = tr["xy"][i]
    if math.hypot(x - fx, y - fy) <= radius:
      label = [lb for lb in tr["labels"] if lb[0] <= step][-1]
      out.append({"name": name, "activity": activity_text(_parse_label(label))})
  return out


def _parse_label(label):
  return parse_description(label[2])


def is_interesting_memory(m, focal):
  if m["type"] in ("thought", "chat"):
    return True
  # Skip object-state events such as "bed is idle".
  if ":" in m["subject"] or m["predicate"] == "is" and m["object"] == "idle":
    return False
  return m["subject"] == focal or m["poignancy"] >= 4


def select_memories(seg, focal, step0, step1, max_n):
  cands = [m for m in seg["memories"]
           if step0 <= m["step"] <= step1 and is_interesting_memory(m, focal)]
  seen, uniq = set(), []
  for m in reversed(cands):  # prefer the newest copy of repeated events
    if m["description"] not in seen:
      seen.add(m["description"])
      uniq.append(m)
  score = lambda m: m["poignancy"] + (3 if m["type"] == "thought" else 0) + (2 if m["subject"] == focal else 0)
  top = sorted(uniq, key=score, reverse=True)[:max_n]
  return sorted(top, key=lambda m: (m["created"], m["id"]))


def _monologue_candidates(seg, convs):
  cands = [{"step": seg["step0"], "trigger": "segment_start"}]
  for a in seg["activities"][1:]:
    if not a["chat_with"]:
      cands.append({"step": a["start_step"], "trigger": "activity_change"})
  for c in convs:
    if c["end_step"] < seg["step1"]:
      cands.append({"step": c["end_step"] + 1, "trigger": "after_conversation", "conversation_id": c["id"]})
  return cands


def _place_monologues(cands, convs, min_gap):
  def in_conv(step):
    return any(c["start_step"] <= step <= c["end_step"] for c in convs)
  chosen = []
  for c in sorted(cands, key=lambda c: (TRIGGER_PRIORITY[c["trigger"]], c["step"])):
    if in_conv(c["step"]):
      continue
    if any(abs(c["step"] - o["step"]) < min_gap for o in chosen):
      continue
    chosen.append(c)
  return sorted(chosen, key=lambda c: c["step"])


def build_context(extract, seg, step, trigger, cfg, conversation=None):
  focal = extract["persona"]
  bcfg = cfg["beats"]
  act = _activity_at(seg, step)
  i = seg["activities"].index(act) if act else -1
  prev_act = seg["activities"][i - 1] if i > 0 else None
  next_act = seg["activities"][i + 1] if act and i + 1 < len(seg["activities"]) else None
  # Thoughts about a conversation are created at its end, so look slightly ahead.
  mem_end = step + (2 if trigger == "after_conversation" else 0)
  memories = select_memories(seg, focal, step - bcfg["lookback_steps"], mem_end, bcfg["max_memories"])
  info = extract["persona_info"]
  return {
    "persona": focal,
    "persona_summary": "; ".join(f"{k}: {info[k]}" for k in ("age", "innate", "learned", "currently", "lifestyle") if info.get(k)),
    "time": humanize_time(seg["clock"][step - seg["step0"]]),
    "place": humanize_address(act["address"] if act else ""),
    "activity": activity_text(act),
    "previous_activity": activity_text(prev_act),
    "next_activity": activity_text(next_act),
    "nearby": _nearby(seg, focal, step, bcfg["nearby_tiles"]),
    "memories": [{k: m[k] for k in ("id", "type", "created", "poignancy", "description")} for m in memories],
    "conversation": conversation["lines"] if conversation else [],
    "trigger": trigger,
  }


def prompt_fields(ctx):
  return {
    "persona_name": ctx["persona"],
    "persona_summary": ctx["persona_summary"],
    "time": ctx["time"],
    "place": ctx["place"],
    "activity": ctx["activity"],
    "previous_activity": ctx["previous_activity"],
    "next_activity": ctx["next_activity"],
    "nearby": ", ".join(f"{n['name']} ({n['activity']})" for n in ctx["nearby"]) or "nobody",
    "memories": "\n".join(f"- [{m['created'][11:16]}] {m['description']}" for m in ctx["memories"]) or "- (none)",
    "conversation": "\n".join(f"{ln['speaker']}: {ln['text']}" for ln in ctx["conversation"]) or "(none)",
    "trigger": TRIGGER_NOTES[ctx["trigger"]],
  }


def build_beats(extract, cfg):
  prompt_name = cfg["prompts"]["monologue"]
  template = load_prompt(prompt_name)
  focal = extract["persona"]
  beats = []
  for seg in extract["segments"]:
    convs = [c for c in seg["conversations"] if c["involves_focal"]]
    items = [{"step": c["start_step"], "conversation": c} for c in convs]
    items += _place_monologues(_monologue_candidates(seg, convs), convs, cfg["beats"]["min_gap_steps"])
    items.sort(key=lambda it: (it["step"], "conversation" in it))
    for it in items:
      beat_id = f"b{len(beats) + 1:02d}"
      if "conversation" in it:
        c = it["conversation"]
        beats.append({
          "id": beat_id, "segment": seg["name"], "type": "conversation",
          "step": c["start_step"], "end_step": c["end_step"], "conversation_id": c["id"],
          "lines": [dict(ln) for ln in c["lines"]],
        })
        continue
      conv = next((c for c in convs if c["id"] == it.get("conversation_id")), None)
      ctx = build_context(extract, seg, it["step"], it["trigger"], cfg, conv)
      prompt = render_prompt(template, prompt_fields(ctx))
      beats.append({
        "id": beat_id, "segment": seg["name"], "type": "monologue",
        "step": it["step"], "trigger": it["trigger"], "speaker": focal,
        "context": ctx, "prompt_version": prompt_name,
        "prompt_hash": stable_hash(prompt), "prompt": prompt,
        "text": None, "text_meta": None,
      })
  return {
    "version": BEATS_VERSION,
    "extract_hash": stable_hash(extract),
    "persona": focal,
    "beats": beats,
  }


def format_beat(beat):
  """Human-readable dump of a beat for `reel.py show-context`."""
  out = [f"== {beat['id']} [{beat['segment']}] {beat['type']} @ step {beat['step']}"]
  if beat["type"] == "conversation":
    out.append(f"conversation {beat['conversation_id']} steps {beat['step']}..{beat['end_step']}")
    out += [f"  {ln['speaker']}: {ln['text']}" for ln in beat["lines"]]
    return "\n".join(out)
  ctx = beat["context"]
  out.append(f"trigger: {beat['trigger']}   prompt: {beat['prompt_version']} ({beat['prompt_hash']})")
  for k in ("time", "place", "activity", "previous_activity", "next_activity"):
    out.append(f"{k:>18}: {ctx[k]}")
  out.append(f"{'nearby':>18}: " + (", ".join(f"{n['name']} ({n['activity']})" for n in ctx["nearby"]) or "nobody"))
  out.append("memories:")
  out += [f"  {m['id']:>9} {m['type']:<7} p{m['poignancy']} {m['created'][11:]}  {m['description']}" for m in ctx["memories"]]
  if ctx["conversation"]:
    out.append(f"conversation: {len(ctx['conversation'])} lines")
  out.append("--- prompt ---")
  out.append(beat["prompt"].rstrip())
  out.append("--- text ---")
  out.append(beat["text"] or "(not generated)")
  return "\n".join(out)
