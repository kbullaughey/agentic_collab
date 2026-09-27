"""Stage 5: synthesize speech with Inworld TTS and get word timestamps.

Uses the Inworld TTS REST API (POST /tts/v1/voice). Clips are cached by
(text, voice, model, rate), so re-running only bills for changed text. Word
timestamps are requested from Inworld (timestampType=WORD). If the response
has none, OpenAI Whisper (whisper-1, word granularity) is used instead.

Writes out/<reel>/audio/<hash>.mp3 and audio/manifest.json:
  {"clips": {"b02.3": {"file", "duration", "words": [[word, t], ...], "voice", "hash", "timestamps"}}}
The keys match timeline speech ids, so `reel.py timeline` picks up real timings.
"""
import base64
import difflib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request

from dotenv import load_dotenv

from .config import REPO_ROOT, stable_hash, write_json

TTS_URL = "https://api.inworld.ai/tts/v1/voice"
MAX_TEXT_CHARS = 2000
TIMEOUT_S = 120


class InworldClient:
  def __init__(self, api_key):
    if api_key.lower().startswith("basic "):
      api_key = api_key.split(None, 1)[1]
    self.api_key = api_key

  def synthesize(self, text, voice_id, model_id, speaking_rate=None, language=None):
    """Return (mp3 bytes, word timings [[word, start_s], ...] or None)."""
    if len(text) > MAX_TEXT_CHARS:
      raise ValueError(f"text longer than {MAX_TEXT_CHARS} chars; split it into smaller beats")
    audio_config = {"audioEncoding": "MP3"}
    if speaking_rate:
      audio_config["speakingRate"] = speaking_rate
    payload = {"text": text, "voiceId": voice_id, "modelId": model_id, "audioConfig": audio_config,
               "deliveryMode": "BALANCED", "timestampType": "WORD"}
    if language:
      payload["language"] = language
    req = urllib.request.Request(TTS_URL, data=json.dumps(payload).encode(), method="POST", headers={
      "Authorization": f"Basic {self.api_key}", "Content-Type": "application/json"})
    try:
      with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
      raise SystemExit(f"Inworld API error {exc.code}: {exc.read().decode(errors='replace')[:1000]}") from exc
    if not result.get("audioContent"):
      raise SystemExit(f"Inworld response missing audioContent: {json.dumps(result)[:500]}")
    return base64.b64decode(result["audioContent"]), parse_inworld_words(result)


def parse_inworld_words(result):
  align = (result.get("timestampInfo") or {}).get("wordAlignment") or {}
  words, starts = align.get("words"), align.get("wordStartTimeSeconds")
  if not words or not starts or len(words) != len(starts):
    return None
  return [[w, round(float(t), 3)] for w, t in zip(words, starts)]


def mp3_duration(path):
  out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
  return float(out.stdout.strip())


def whisper_words(path):
  """Word start times from OpenAI Whisper (the fallback when Inworld gives none)."""
  from openai import OpenAI
  load_dotenv(REPO_ROOT / ".env")
  client = OpenAI()
  with open(path, "rb") as f:
    tr = client.audio.transcriptions.create(model="whisper-1", file=f, response_format="verbose_json",
                                            timestamp_granularities=["word"])
  return [[w.word, round(w.start, 3)] for w in tr.words]


def _norm(w):
  return re.sub(r"[^a-z0-9']", "", w.lower())


def align_words(text, timed):
  """Put times from `timed` ([[word, t]]) onto the words of `text`.

  TTS/ASR tokens can differ from the script (punctuation, numbers), so tokens
  are matched with difflib, and any unmatched script words are interpolated."""
  script = re.findall(r"\S+", text)
  a, b = [_norm(w) for w in script], [_norm(w) for w, _ in timed]
  times = [None] * len(script)
  for blk in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks():
    for k in range(blk.size):
      times[blk.a + k] = timed[blk.b + k][1]
  known = [i for i, t in enumerate(times) if t is not None]
  if not known:
    return None
  for i in range(len(times)):
    if times[i] is None:
      prev = max((k for k in known if k < i), default=None)
      nxt = min((k for k in known if k > i), default=None)
      if prev is None:
        times[i] = times[nxt]
      elif nxt is None:
        times[i] = times[prev]
      else:
        times[i] = times[prev] + (times[nxt] - times[prev]) * (i - prev) / (nxt - prev)
  for i in range(1, len(times)):  # keep monotonic
    times[i] = max(times[i], times[i - 1])
  return [[w, round(t, 3)] for w, t in zip(script, times)]


def speech_items(beats):
  """(speech id, speaker, text, is_monologue) with ids matching the timeline."""
  for b in beats["beats"]:
    if b["type"] == "conversation":
      for k, ln in enumerate(b["lines"]):
        yield f"{b['id']}.{k}", ln["speaker"], ln["text"], False
    elif b.get("text"):
      yield f"{b['id']}.0", b["speaker"], b["text"], True


def voice_for(cfg, speaker, is_monologue):
  voices = cfg["voices"]
  v = voices.get("_monologue") if is_monologue else None
  return v or voices.get(speaker)


def synthesize(cfg, beats, audio_dir, only=None, dry_run=False, client=None, words_fallback=whisper_words):
  tcfg = cfg["tts"]
  audio_dir.mkdir(parents=True, exist_ok=True)
  manifest_path = audio_dir / "manifest.json"
  manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"clips": {}}
  items = [it for it in speech_items(beats) if not only or it[0].split(".")[0] in only]

  missing = sorted({spk for _, spk, _, mono in items if not voice_for(cfg, spk, mono)})
  if missing:
    raise SystemExit(f"no voice configured for {missing}; add them under `voices:` in the config")

  todo, chars = [], 0
  for sid, spk, text, mono in items:
    voice = voice_for(cfg, spk, mono)
    h = stable_hash([text, voice, tcfg["model"], tcfg.get("speaking_rate")])
    clip = manifest["clips"].get(sid)
    if clip and clip.get("hash") == h and (audio_dir / clip["file"]).exists():
      continue
    todo.append((sid, spk, text, voice, h))
    chars += len(text)

  by_voice = {}
  for _, _, text, voice, _ in todo:
    by_voice[voice] = by_voice.get(voice, 0) + len(text)
  print(f"{len(todo)} of {len(items)} clips need synthesis, {chars} characters "
        f"({', '.join(f'{v}: {n}' for v, n in sorted(by_voice.items())) or 'none'})")
  rate = tcfg.get("usd_per_million_chars")
  if rate:
    print(f"estimated cost: ${chars * rate / 1e6:.4f}")
  if dry_run or not todo:
    return manifest

  if client is None:
    load_dotenv(REPO_ROOT / ".env")
    key = os.environ.get("INWORLD_API_KEY", "").strip()
    if not key:
      raise SystemExit(f"INWORLD_API_KEY is not set; add it to {REPO_ROOT / '.env'} or the environment")
    client = InworldClient(key)

  for sid, spk, text, voice, h in todo:
    mp3, words = client.synthesize(text, voice, tcfg["model"], tcfg.get("speaking_rate"), tcfg.get("language"))
    path = audio_dir / f"{h}.mp3"
    path.write_bytes(mp3)
    source = "inworld"
    if not words:
      words, source = words_fallback(path), "whisper"
    manifest["clips"][sid] = {
      "file": path.name, "duration": round(mp3_duration(path), 3),
      "words": align_words(text, words) if words else None,
      "voice": voice, "speaker": spk, "hash": h, "timestamps": source if words else "none",
    }
    write_json(manifest_path, manifest)
    print(f"  {sid} {spk} ({voice}): {manifest['clips'][sid]['duration']:.2f}s, timestamps from {source}")
  return manifest
