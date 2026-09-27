import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reelkit.config import DEFAULTS, _merge
from reelkit.timeline import build_timeline
from reelkit.tts import align_words, parse_inworld_words, synthesize
from reelkit.validate import validate

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def test_align_words_handles_token_mismatch():
  timed = [["good", 0.0], ["morning", 0.3], ["did", 0.9], ["you", 1.0], ["sleep", 1.2], ["well", 1.5]]
  out = align_words("Good morning, my dear. Did you sleep well?", timed)
  assert [w for w, _ in out] == ["Good", "morning,", "my", "dear.", "Did", "you", "sleep", "well?"]
  times = [t for _, t in out]
  assert times[0] == 0.0 and times[4] == 0.9 and times == sorted(times)
  assert 0.3 < times[2] < times[3] < 0.9  # interpolated


def test_parse_inworld_words():
  res = {"timestampInfo": {"wordAlignment": {"words": ["Hi", "there"], "wordStartTimeSeconds": [0.1, 0.4],
                                             "wordEndTimeSeconds": [0.3, 0.8]}}}
  assert parse_inworld_words(res) == [["Hi", 0.1], ["there", 0.4]]
  assert parse_inworld_words({"audioContent": "x"}) is None


class FakeClient:
  def __init__(self, tmp):
    self.calls = []
    self.mp3 = tmp / "tone.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=1.5", str(self.mp3)], check=True)

  def synthesize(self, text, voice, model, rate=None, language=None):
    self.calls.append((text, voice))
    words = text.split()
    return self.mp3.read_bytes(), [[w, round(1.4 * i / len(words), 3)] for i, w in enumerate(words)]


def test_synthesize_caches_and_feeds_timeline(tmp_path):
  from reelkit.beats import build_beats
  from reelkit.extract import extract
  from test_pipeline import FIXTURE, make_cfg  # noqa: F401
  cfg = make_cfg(voices={"Sam Moore": "Dennis", "Jennifer Moore": "Sarah"})
  ex = extract(cfg)
  beats = build_beats(ex, cfg)
  for b in beats["beats"]:
    if b["type"] == "monologue":
      b["text"] = "Pancakes again. Jennifer will like that."
  client = FakeClient(tmp_path)
  audio_dir = tmp_path / "audio"
  manifest = synthesize(cfg, beats, audio_dir, client=client, words_fallback=None)
  n = len(client.calls)
  assert n == 16 + sum(b["type"] == "monologue" for b in beats["beats"])
  assert manifest["clips"]["b02.0"]["duration"] == pytest.approx(1.5, abs=0.1)
  synthesize(cfg, beats, audio_dir, client=client, words_fallback=None)
  assert len(client.calls) == n  # cached
  tl = build_timeline(ex, beats, DEFAULTS["pacing"], manifest["clips"])
  assert [lvl for lvl, _ in validate(ex, beats, tl)] == []
  line = next(s for s in tl["speech"] if s["id"] == "b02.0")
  assert line["t1"] - line["t0"] == pytest.approx(manifest["clips"]["b02.0"]["duration"])


def test_missing_voice_is_reported(tmp_path):
  from test_pipeline import make_cfg
  cfg = _merge(make_cfg(), {"voices": {"Sam Moore": "Dennis"}})
  beats = {"beats": [{"id": "b01", "type": "conversation", "lines": [{"speaker": "Jennifer Moore", "text": "Hi"}]}]}
  with pytest.raises(SystemExit, match="Jennifer Moore"):
    synthesize(cfg, beats, tmp_path, dry_run=True)
