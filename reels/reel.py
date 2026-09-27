#!/usr/bin/env python
"""Reel CLI: build persona-following replays of saved simulations.

Stages (each writes one file under reels/out/<reel>/):
  extract    sim history          -> extract.json
  beats      extract.json         -> beats.json    (monologue prompts + conversations)
  monologue  beats.json           -> beats.json    (fills monologue text via the LLM)
  tts        beats.json           -> audio/        (Inworld TTS + word timings)
  timeline   extract+beats(+audio)-> timeline.json (reel time <-> sim steps)
  render     everything           -> reel.mp4

Inspection: show-context, validate, report, serve.
Example:
  uv run python reels/reel.py extract reels/configs/sam_morning.yaml
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reelkit import config as C


def _paths(cfg):
  d = C.out_dir(cfg)
  return {k: d / f"{k}.json" for k in ("extract", "beats", "timeline")} | {"dir": d}


def _load(path, what):
  if not path.exists():
    sys.exit(f"missing {path.name}; run `reel.py {what}` first")
  return C.read_json(path)


def _audio_manifest(paths):
  p = paths["dir"] / "audio" / "manifest.json"
  return C.read_json(p)["clips"] if p.exists() else None


def cmd_extract(cfg, args):
  from reelkit.extract import extract
  paths = _paths(cfg)
  ex = extract(cfg)
  C.write_json(paths["extract"], ex)
  for seg in ex["segments"]:
    convs = [c for c in seg["conversations"] if c["involves_focal"]]
    print(f"{seg['name']}: steps {seg['step0']}..{seg['step1']} ({seg['clock'][0]} .. {seg['clock'][-1]}), "
          f"{len(seg['activities'])} activities, {len(convs)} conversations, {len(seg['memories'])} memories")
  print(f"wrote {paths['extract']}")


def cmd_beats(cfg, args):
  from reelkit.beats import build_beats
  paths = _paths(cfg)
  ex = _load(paths["extract"], "extract")
  new = build_beats(ex, cfg)
  kept = 0
  if paths["beats"].exists() and not args.force:
    # Keep generated or hand-written text for beats whose prompt is unchanged.
    old = {(b["segment"], b["step"], b.get("prompt_hash")): b for b in C.read_json(paths["beats"])["beats"]}
    for b in new["beats"]:
      prev = old.get((b["segment"], b["step"], b.get("prompt_hash")))
      if b["type"] == "monologue" and prev and prev.get("text"):
        b["text"], b["text_meta"] = prev["text"], prev.get("text_meta")
        kept += 1
  C.write_json(paths["beats"], new)
  for b in new["beats"]:
    desc = f"{b['conversation_id']} ({len(b['lines'])} lines)" if b["type"] == "conversation" else b["trigger"]
    print(f"  {b['id']} [{b['segment']}] step {b['step']}: {b['type']} {desc}")
  print(f"wrote {paths['beats']} ({len(new['beats'])} beats, kept text for {kept})")


def cmd_show_context(cfg, args):
  from reelkit.beats import format_beat
  beats = _load(_paths(cfg)["beats"], "beats")["beats"]
  sel = [b for b in beats if not args.beat or b["id"] in args.beat]
  if not sel:
    sys.exit(f"no beats match {args.beat}")
  print("\n\n".join(format_beat(b) for b in sel))


def cmd_monologue(cfg, args):
  from reelkit.monologue import generate
  paths = _paths(cfg)
  beats = _load(paths["beats"], "beats")
  generate(cfg, beats, paths, only=args.beat, redo=args.redo, dry_run=args.dry_run)


def cmd_timeline(cfg, args):
  from reelkit.timeline import build_timeline
  paths = _paths(cfg)
  ex = _load(paths["extract"], "extract")
  beats = _load(paths["beats"], "beats")
  audio = None if args.estimate else _audio_manifest(paths)
  tl = build_timeline(ex, beats, cfg["pacing"], audio)
  tl["camera"] = cfg["camera"]
  C.write_json(paths["timeline"], tl)
  for s in tl["segments"]:
    print(f"  {s['name']}: {s['t1'] - s['t0']:.1f}s")
  print(f"wrote {paths['timeline']} ({tl['duration']:.1f}s, {len(tl['speech'])} speech items, "
        f"timing from {tl['timing_source']})")


def cmd_validate(cfg, args):
  from reelkit.validate import validate
  paths = _paths(cfg)
  ex = _load(paths["extract"], "extract")
  beats = C.read_json(paths["beats"]) if paths["beats"].exists() else None
  tl = C.read_json(paths["timeline"]) if paths["timeline"].exists() and beats else None
  issues = validate(ex, beats, tl)
  for level, msg in issues:
    print(f"{level}: {msg}")
  n_err = sum(1 for level, _ in issues if level == "error")
  checked = ", ".join(n for n, v in (("extract", ex), ("beats", beats), ("timeline", tl)) if v)
  print(f"checked {checked}: {n_err} errors, {len(issues) - n_err} warnings")
  sys.exit(1 if n_err else 0)


def cmd_report(cfg, args):
  from reelkit.validate import report
  paths = _paths(cfg)
  print(report(_load(paths["extract"], "extract"), _load(paths["beats"], "beats"),
               _load(paths["timeline"], "timeline")))


def cmd_serve(cfg, args):
  from reelkit.serve import serve
  serve(cfg, _paths(cfg)["dir"], args.port)


def cmd_tts(cfg, args):
  from reelkit.tts import synthesize
  paths = _paths(cfg)
  synthesize(cfg, _load(paths["beats"], "beats"), paths["dir"] / "audio",
             only=args.beat, dry_run=args.dry_run)


def cmd_render(cfg, args):
  from reelkit.render import render
  paths = _paths(cfg)
  render(cfg, paths["dir"], _load(paths["timeline"], "timeline"), fps=args.fps,
         segment=args.segment, port=args.port, keep_frames=args.keep_frames)


def main(argv=None):
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  sub = ap.add_subparsers(dest="cmd", required=True)

  def add(name, fn, help_):
    p = sub.add_parser(name, help=help_)
    p.add_argument("config", help="reel config YAML (e.g. reels/configs/sam_morning.yaml)")
    p.set_defaults(fn=fn)
    return p

  add("extract", cmd_extract, "extract sim history into extract.json")
  p = add("beats", cmd_beats, "build beats.json (conversations + monologue prompts)")
  p.add_argument("--force", action="store_true", help="discard existing monologue text")
  p = add("show-context", cmd_show_context, "print the context and prompt of beats")
  p.add_argument("beat", nargs="*", help="beat ids (default: all)")
  p = add("monologue", cmd_monologue, "generate monologue text with the LLM")
  p.add_argument("--beat", nargs="*", help="only these beat ids")
  p.add_argument("--redo", action="store_true", help="regenerate beats that already have text")
  p.add_argument("--dry-run", action="store_true", help="show what would be generated")
  p = add("timeline", cmd_timeline, "build timeline.json")
  p.add_argument("--estimate", action="store_true", help="ignore TTS audio and use the fixed speaking rate")
  add("validate", cmd_validate, "check stage files for consistency")
  add("report", cmd_report, "summarize durations, pacing and text difficulty")
  p = add("serve", cmd_serve, "serve the viewer for interactive preview")
  p.add_argument("--port", type=int, default=8765)
  p = add("tts", cmd_tts, "synthesize speech with Inworld")
  p.add_argument("--beat", nargs="*", help="only these beat ids")
  p.add_argument("--dry-run", action="store_true", help="print character counts only")
  p = add("render", cmd_render, "render the reel to video")
  p.add_argument("--fps", type=int, default=30)
  p.add_argument("--segment", help="only render this segment")
  p.add_argument("--port", type=int, default=8766)
  p.add_argument("--keep-frames", action="store_true")

  args = ap.parse_args(argv)
  args.fn(C.load_config(args.config), args)


if __name__ == "__main__":
  main()
