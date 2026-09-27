"""Stage 4: map reel time onto sim steps, paced by speech.

The output is a list of piecewise-linear spans (reel time -> fractional sim
step, per segment) plus speech entries with word-level reel times. While
someone speaks the sim is slowed or held so the speech fits; walking with no
speech is sped up; idle stretches with no speech are squeezed into at most
`max_idle_s` seconds. Every segment fades in and out.

Speech durations come from a fixed characters-per-minute rate, or from the
TTS audio manifest when one is supplied.
"""
import re

from .config import stable_hash

TIMELINE_VERSION = 1
PLACEHOLDER_CHARS = 200


def estimate_words(text, duration):
  """Spread words over `duration` proportionally to their character offsets."""
  words = [(m.group(0), m.start()) for m in re.finditer(r"\S+", text)]
  n = max(len(text), 1)
  return [[w, round(duration * off / n, 3)] for w, off in words]


def speech_timing(text, key, pacing, audio):
  """Return (duration, words relative to the clip start, audio ref or None)."""
  clip = (audio or {}).get(key)
  if clip:
    words = clip.get("words") or estimate_words(text, clip["duration"])
    return clip["duration"], words, {"file": clip["file"]}
  duration = len(text) / (pacing["chars_per_min"] / 60.0)
  return duration, estimate_words(text, duration), None


class _Builder:
  def __init__(self, pacing, audio):
    self.p = pacing
    self.audio = audio
    self.t = 0.0
    self.spans = []
    self.speech = []

  def span(self, seg_i, s0, s1, dur, mode):
    if dur <= 0:
      return
    self.spans.append({"seg": seg_i, "t0": round(self.t, 3), "t1": round(self.t + dur, 3),
                       "s0": s0, "s1": s1, "mode": mode})
    self.t += dur

  def add_speech(self, seg_i, beat, key, kind, speaker, text, t0, placeholder=False):
    dur, words, audio = speech_timing(text, key, self.p, self.audio)
    self.speech.append({
      "id": key, "beat_id": beat["id"], "seg": seg_i, "kind": kind, "speaker": speaker,
      "text": text, "t0": round(t0, 3), "t1": round(t0 + dur, 3),
      "words": [[w, round(t0 + wt, 3)] for w, wt in words],
      "audio": audio, "placeholder": placeholder,
    })
    return dur

  def fill(self, seg_i, xy, step0, a, b):
    """Advance from step a to b with no speech: walking is fast, idling is elided."""
    if b <= a:
      return
    fast_rate = self.p["base_steps_per_s"] * self.p["walk_speedup"]
    moving = [xy[k + 1 - step0] != xy[k - step0] for k in range(a, b)]
    runs = []  # [moving, start_step, n_steps]
    for k, mv in zip(range(a, b), moving):
      if runs and runs[-1][0] == mv:
        runs[-1][2] += 1
      else:
        runs.append([mv, k, 1])
    merged = []
    for r in runs:
      if merged and r[2] < self.p["min_run_steps"]:
        merged[-1][2] += r[2]
      elif merged and merged[-1][2] < self.p["min_run_steps"]:
        merged[-1] = [r[0], merged[-1][1], merged[-1][2] + r[2]]
      else:
        merged.append(list(r))
    for mv, start, n in merged:
      dur = n / fast_rate
      if mv or dur <= self.p["max_idle_s"]:
        self.span(seg_i, start, start + n, dur, "fast")
      else:
        self.span(seg_i, start, start + n, self.p["max_idle_s"], "elide")


def build_timeline(extract, beats, pacing, audio=None):
  b = _Builder(pacing, audio)
  segments = []
  fade = pacing["fade_s"] / 2
  for seg_i, seg in enumerate(extract["segments"]):
    focal_xy = seg["tracks"][extract["persona"]]["xy"]
    s0, s1 = seg["step0"], seg["step1"]
    seg_t0 = b.t
    b.span(seg_i, s0, s0, fade, "fade_in")
    blocks = sorted((bt for bt in beats["beats"] if bt["segment"] == seg["name"]), key=lambda bt: bt["step"])
    cursor = s0
    for j, beat in enumerate(blocks):
      start = max(beat["step"], cursor)
      b.fill(seg_i, focal_xy, s0, cursor, min(start, s1))
      cursor = min(start, s1)
      t = b.t + pacing["lead_in_s"]
      if beat["type"] == "conversation":
        for k, ln in enumerate(beat["lines"]):
          t += b.add_speech(seg_i, beat, f"{beat['id']}.{k}", "line", ln["speaker"], ln["text"], t)
          t += pacing["min_gap_s"]
        end = min(max(beat["end_step"] + 1, cursor), s1)
      else:
        text, placeholder = beat.get("text"), False
        if not text:
          text, placeholder = f"({beat['id']}: monologue not generated yet) " + "." * PLACEHOLDER_CHARS, True
        t += b.add_speech(seg_i, beat, f"{beat['id']}.0", "monologue", beat["speaker"], text, t, placeholder)
        t += pacing["min_gap_s"]
        next_step = blocks[j + 1]["step"] if j + 1 < len(blocks) else s1
        dur = t - b.t
        end = min(cursor + round(dur * pacing["base_steps_per_s"]), max(next_step, cursor), s1)
      b.span(seg_i, cursor, end, t - b.t, "speech" if end > cursor else "hold")
      cursor = end
    b.fill(seg_i, focal_xy, s0, cursor, s1)
    b.span(seg_i, s1, s1, fade, "fade_out")
    segments.append({"name": seg["name"], "t0": round(seg_t0, 3), "t1": round(b.t, 3),
                     "step0": s0, "step1": s1})
  return {
    "version": TIMELINE_VERSION,
    "extract_hash": stable_hash(extract),
    "beats_hash": stable_hash(beats),
    "timing_source": "tts" if audio else "estimate",
    "pacing": pacing,
    "duration": round(b.t, 3),
    "segments": segments,
    "spans": b.spans,
    "speech": b.speech,
  }


def step_at(timeline, t):
  """(seg index, fractional step) at reel time t; mirrors the viewer's logic."""
  spans = timeline["spans"]
  for sp in spans:
    if sp["t0"] <= t < sp["t1"]:
      f = (t - sp["t0"]) / (sp["t1"] - sp["t0"])
      return sp["seg"], sp["s0"] + f * (sp["s1"] - sp["s0"])
  last = spans[-1]
  return last["seg"], float(last["s1"])
