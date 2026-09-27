"""Stage 7: render the reel to video.

Playwright drives the viewer in capture mode, seeking to each frame's reel
time and screenshotting the stage. Frames are piped into ffmpeg, and TTS clips
(if any) are mixed in at their reel start times.
"""
import asyncio
import json
import shutil
import subprocess
import time
from pathlib import Path

from .serve import serve_in_background

STAGE_W, STAGE_H = 1600, 900


def _audio_inputs(timeline, out_dir, t0, t1):
  clips = []
  for s in timeline["speech"]:
    if s.get("audio") and t0 <= s["t0"] < t1:
      path = Path(out_dir) / "audio" / s["audio"]["file"]
      if not path.exists():
        raise FileNotFoundError(f"missing audio clip {path}")
      clips.append((path, s["t0"] - t0))
  return clips


def _ffmpeg_cmd(out_path, fps, clips, duration):
  cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps),
         "-c:v", "mjpeg", "-i", "-"]
  for path, _ in clips:
    cmd += ["-i", str(path)]
  if clips:
    parts = [f"[{i + 1}:a]adelay={int(off * 1000)}:all=1[a{i}]" for i, (_, off) in enumerate(clips)]
    mix = "".join(f"[a{i}]" for i in range(len(clips)))
    parts.append(f"{mix}amix=inputs={len(clips)}:normalize=0,apad[aout]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[aout]", "-c:a", "aac", "-b:a", "160k"]
  cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium",
          "-t", f"{duration:.3f}", "-movflags", "+faststart", str(out_path)]
  return cmd


async def _capture(port, fps, t0, t1, sink, keep_dir=None):
  from playwright.async_api import async_playwright
  async with async_playwright() as p:
    browser = await p.chromium.launch()
    page = await browser.new_page(viewport={"width": STAGE_W, "height": STAGE_H})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    await page.goto(f"http://127.0.0.1:{port}/viewer/index.html?capture=1")
    await page.wait_for_function("window.reel && window.reel.ready", timeout=60000)
    stage = page.locator("#stage")
    n = round((t1 - t0) * fps)
    started = time.time()
    for k in range(n):
      await page.evaluate(f"window.reel.seek({t0 + k / fps})")
      jpg = await stage.screenshot(type="jpeg", quality=92)
      sink(jpg)
      if keep_dir:
        (keep_dir / f"{k:06d}.jpg").write_bytes(jpg)
      if k % (fps * 10) == 0:
        el = time.time() - started
        print(f"  frame {k}/{n}  ({el:.0f}s elapsed, ~{el / max(k, 1) * (n - k):.0f}s left)", flush=True)
    await browser.close()
    if errors:
      raise RuntimeError(f"viewer errors during capture: {errors[:3]}")
    return n


def render(cfg, out_dir, timeline, fps=30, segment=None, port=8766, keep_frames=False):
  if not shutil.which("ffmpeg"):
    raise SystemExit("ffmpeg not found on PATH")
  out_dir = Path(out_dir)
  if segment:
    seg = next((s for s in timeline["segments"] if s["name"] == segment), None)
    if seg is None:
      raise SystemExit(f"unknown segment '{segment}'; have {[s['name'] for s in timeline['segments']]}")
    t0, t1, name = seg["t0"], seg["t1"], f"reel_{segment}"
  else:
    t0, t1, name = 0.0, timeline["duration"], "reel"
  out_path = out_dir / f"{name}.mp4"
  clips = _audio_inputs(timeline, out_dir, t0, t1)
  keep_dir = None
  if keep_frames:
    keep_dir = out_dir / f"frames_{name}"
    keep_dir.mkdir(exist_ok=True)

  srv = serve_in_background(out_dir, port)
  proc = subprocess.Popen(_ffmpeg_cmd(out_path, fps, clips, t1 - t0), stdin=subprocess.PIPE)
  print(f"rendering {name}: {t1 - t0:.1f}s at {fps} fps, {len(clips)} audio clips -> {out_path}")
  try:
    n = asyncio.run(_capture(port, fps, t0, t1, proc.stdin.write, keep_dir))
  finally:
    proc.stdin.close()
    proc.wait()
    srv.shutdown()
  if proc.returncode:
    raise SystemExit(f"ffmpeg failed with code {proc.returncode}")
  meta = {"file": out_path.name, "frames": n, "fps": fps, "t0": t0, "t1": t1,
          "audio_clips": len(clips), "timing_source": timeline["timing_source"]}
  (out_dir / f"{name}.json").write_text(json.dumps(meta, indent=1))
  print(f"wrote {out_path} ({n} frames)")
