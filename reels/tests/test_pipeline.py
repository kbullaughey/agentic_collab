import copy
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reelkit.beats import build_beats
from reelkit.config import DEFAULTS, _merge
from reelkit.extract import extract, parse_description
from reelkit.sim import Sim
from reelkit.timeline import build_timeline, estimate_words, step_at
from reelkit.validate import validate

FIXTURE = Path(__file__).parent / "fixtures" / "mini_sim"


def make_cfg(**over):
  cfg = _merge(DEFAULTS, {"sim": str(FIXTURE), "persona": "Sam Moore",
                          "segments": [{"name": "breakfast", "steps": [1795, 1850]}]})
  cfg = _merge(cfg, over)
  cfg["name"] = "test"
  return cfg


@pytest.fixture(scope="module")
def sim():
  return Sim(str(FIXTURE))


@pytest.fixture(scope="module")
def ex(sim):
  return extract(make_cfg(), sim)


def test_parse_description():
  d = parse_description("waking up and completing his morning routine (brushing his teeth) @ the Ville:house:bathroom:sink")
  assert d["act"] == "waking up and completing his morning routine"
  assert d["sub_act"] == "brushing his teeth"
  assert d["address"] == "the Ville:house:bathroom:sink"
  assert parse_description("conversing about pancakes @ <persona> Jennifer Moore")["chat_with"] == "Jennifer Moore"


def test_clock_is_read_per_step_not_assumed_linear(sim):
  # The sim clock jumps from 05:59:10 to 06:00:00 at step 2156.
  assert sim.time_at(2155) == datetime(2023, 2, 13, 5, 59, 10)
  assert sim.time_at(2156) == datetime(2023, 2, 13, 6, 0, 0)
  assert sim.step_at(datetime(2023, 2, 13, 5, 59, 30)) == 2155
  assert sim.step_at(datetime(2023, 2, 13, 5, 0, 20)) == 1802


def test_conversation_deduped_and_linked_to_chat_node(ex):
  seg = ex["segments"][0]
  convs = [c for c in seg["conversations"] if c["involves_focal"]]
  assert len(convs) == 1
  c = convs[0]
  assert (c["start_step"], c["end_step"]) == (1801, 1841)
  assert c["participants"] == ["Sam Moore", "Jennifer Moore"]
  assert len(c["lines"]) == 16 and c["lines"][0]["speaker"] == "Sam Moore"
  assert c["chat_nodes"] == ["node_23"]


def test_memories_map_to_steps_and_drop_junk(ex):
  mems = {m["id"]: m for m in ex["segments"][0]["memories"]}
  assert mems["node_23"]["step"] == 1802
  assert mems["node_32"]["type"] == "thought" and mems["node_32"]["evidence"] == ["node_23"]
  assert not any("this is blank" in m["description"] for m in mems.values())


def test_node_based_segment(sim):
  cfg = make_cfg(segments=[{"name": "n", "nodes": ["node_23", "node_32"], "pad_steps": 5}])
  seg = extract(cfg, sim)["segments"][0]
  assert (seg["step0"], seg["step1"]) == (1797, 1846)


def test_beats_place_monologues_outside_conversations(ex):
  beats = build_beats(ex, make_cfg())["beats"]
  kinds = [(b["type"], b["step"], b.get("trigger")) for b in beats]
  assert kinds[0] == ("monologue", 1795, "segment_start")
  assert ("conversation", 1801, None) in kinds
  assert ("monologue", 1842, "after_conversation") in kinds
  for b in beats:
    if b["type"] == "monologue":
      assert not (1801 <= b["step"] <= 1841)
      assert "$" not in b["prompt"]
  after = next(b for b in beats if b.get("trigger") == "after_conversation")
  assert "node_32" in [m["id"] for m in after["context"]["memories"]]
  assert len(after["context"]["conversation"]) == 16


@pytest.fixture(scope="module")
def beats(ex):
  b = build_beats(ex, make_cfg())
  for bt in b["beats"]:
    if bt["type"] == "monologue":
      bt["text"] = "The kitchen smells like pancakes. Jennifer looks happy today."
  return b


def test_timeline_is_valid_and_speech_holds_the_sim(ex, beats):
  tl = build_timeline(ex, beats, DEFAULTS["pacing"])
  assert [lvl for lvl, _ in validate(ex, beats, tl)] == []
  conv = [s for s in tl["speech"] if s["beat_id"] == "b02"]
  assert len(conv) == 16
  # The conversation's sim steps are stretched over the whole spoken exchange.
  span = next(sp for sp in tl["spans"] if sp["s0"] == 1801)
  assert span["mode"] == "speech" and span["s1"] == 1842
  assert span["t0"] <= conv[0]["t0"] and conv[-1]["t1"] <= span["t1"]
  seg, s = step_at(tl, (conv[0]["t0"] + conv[-1]["t1"]) / 2)
  assert seg == 0 and 1801 < s < 1842


def test_timeline_uses_audio_durations(ex, beats):
  audio = {"b02.0": {"file": "b02.0.mp3", "duration": 9.0,
                     "words": [["Good", 0.0], ["morning,", 0.4]]}}
  tl = build_timeline(ex, beats, DEFAULTS["pacing"], audio)
  line = next(s for s in tl["speech"] if s["id"] == "b02.0")
  assert line["t1"] - line["t0"] == pytest.approx(9.0)
  assert line["audio"] == {"file": "b02.0.mp3"}
  assert tl["timing_source"] == "tts"


def test_idle_stretch_is_elided(ex):
  # No beats at all: the sim mostly idles, so time is squeezed.
  tl = build_timeline(ex, {"beats": []}, DEFAULTS["pacing"])
  assert any(sp["mode"] == "elide" for sp in tl["spans"])
  assert tl["duration"] < 55 / DEFAULTS["pacing"]["base_steps_per_s"]


def test_estimate_words_monotonic():
  words = estimate_words("one two three four", 4.0)
  times = [t for _, t in words]
  assert times == sorted(times) and times[0] == 0 and times[-1] < 4.0


def test_validate_catches_seeded_errors(ex, beats):
  tl = build_timeline(ex, beats, DEFAULTS["pacing"])
  bad = copy.deepcopy(tl)
  bad["spans"][2]["t0"] += 0.5
  bad["speech"][1]["t0"] = bad["speech"][0]["t0"]
  msgs = " ".join(m for lvl, m in validate(ex, beats, bad) if lvl == "error")
  assert "gap/overlap" in msgs and "overlap" in msgs
  bad_ex = copy.deepcopy(ex)
  bad_ex["segments"][0]["tracks"]["Sam Moore"]["xy"][3] = [500, 5]
  assert any("off the map" in m for _, m in validate(bad_ex))
