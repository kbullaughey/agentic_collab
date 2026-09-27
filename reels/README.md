# Reels

Short videos made from saved simulations for English learners (see `../REELS.md` for the design).
A reel follows one persona, adds an LLM-written inner monologue, and plays conversations line by line in a chat panel.
Its clock is paced by speech, not by the sim clock.

## Quick start

```bash
C=reels/configs/sam_morning.yaml
uv run python reels/reel.py extract   $C   # sim history      -> out/<reel>/extract.json
uv run python reels/reel.py beats     $C   # monologue prompts + conversations -> beats.json
uv run python reels/reel.py show-context $C b03   # inspect a beat's context and prompt
uv run python reels/reel.py monologue $C   # LLM fills monologue text (cost -> cost.json)
uv run python reels/reel.py timeline  $C   # reel time <-> sim steps -> timeline.json
uv run python reels/reel.py validate  $C   # consistency checks (exit 1 on errors)
uv run python reels/reel.py report    $C   # durations, pacing, text difficulty
uv run python reels/reel.py serve     $C   # preview at http://127.0.0.1:8765/
uv run python reels/reel.py tts       $C --dry-run   # character counts per voice
uv run python reels/reel.py tts       $C   # Inworld audio + word timestamps -> audio/
uv run python reels/reel.py timeline  $C   # re-run: now paced by the real audio
uv run python reels/reel.py render    $C [--segment NAME] [--fps 30]   # -> reel.mp4
```

Each stage reads the previous stage's file, so any stage can be re-run and inspected on its own.
Each file records hashes of its inputs, and `validate` warns when a downstream file is stale.

Requirements:
- `OPENAI_API_KEY` in `.env`, for monologues and the Whisper fallback.
- `INWORLD_API_KEY` in `.env`, for TTS.
- `ffmpeg` on `PATH`.
- For rendering, Playwright's Chromium: `uv run playwright install chromium`.

## Config (`configs/<reel>.yaml`)

```yaml
sim: skip-morning-s-14        # code under storage/ or compressed_storage/, or a path
persona: Sam Moore
segments:                     # each segment fades in and out
  - {name: breakfast-chat, steps: [1790, 1900]}
  - {name: park-meeting, nodes: [node_303, node_308], pad_steps: 15}  # by memory node ids
prompts: {monologue: monologue/v1, model: gpt-6-luna}   # prompts/monologue/v1.txt
voices: {Sam Moore: Dennis, Jennifer Moore: Sarah, _monologue: Dennis}
pacing: {chars_per_min: 750, base_steps_per_s: 2, walk_speedup: 4, max_idle_s: 1.5}
camera: {edge_margin_tiles: 6, zoom: 1.0, pan_ms: 600}
beats:  {min_gap_steps: 30, lookback_steps: 90, max_memories: 8}
```

All defaults are listed in `reelkit/config.py`.

## Input: compressed vs. uncompressed history

Prefer uncompressed `storage/<sim>`. Only its per-step movement files carry the real sim clock, and that clock is not linear: `skip-morning-s-14` jumps at steps 2156, 2425 and others.
Compressed sims work too, but they assume `start_date + step * sec_per_step` and print a warning.

## Stage files

- **`extract.json`**, one entry per segment:
  - `clock`: sim time per step.
  - `tracks`: every persona's `xy` per step, plus `labels`, the `[step, emoji, description]` changes.
  - `activities`: the focal persona's action spans.
  - `conversations`: deduped from the movement `chat` field and linked to `chat` memory nodes.
  - `memories`: the focal persona's nodes in the window, with `created` mapped to a step.
- **`beats.json`**: ordered beats.
  - `conversation` beats hold the lines.
  - `monologue` beats are placed at segment start, at activity changes and after conversations. Each holds its `context` (place, activity, nearby personas, selected memories, conversation), the rendered `prompt`, and `text` with `text_meta`.
  - Hand edits are fine. Re-running `beats` keeps text for beats whose prompt is unchanged.
- **`timeline.json`**:
  - `spans` are piecewise-linear maps from reel time to a fractional sim step, with modes `fade_in`, `speech`, `hold`, `fast`, `elide` and `fade_out`.
  - `speech` items carry reel `t0`/`t1`, per-word times, and an optional audio file.
  - Conversations stretch their sim steps over the spoken exchange. Walking with no speech runs at `walk_speedup`, and idle stretches are squeezed to `max_idle_s`.
- **`audio/manifest.json`**: one clip per speech id.
  - Holds the duration and word times.
  - Word times come from Inworld's `timestampType: WORD`, or from Whisper when Inworld returns none.
  - Clips are cached by text, voice, model and rate.

## Viewer

`viewer/` is a static Phaser 3.55 page that uses the game assets from `environment/frontend_server/static_dirs/assets`.
Everything on screen is a pure function of reel time: sprites, walk frames, camera, chat panel and fades.
- The camera follows a precomputed pan path. It re-centres on the persona when they come within `edge_margin_tiles` of an edge, and it is clamped to the map.
- `window.reel.seek(t)` is what `render` uses to capture frames deterministically.

Keys:
- space: play/pause
- ←/→: seek 5 s
- d: debug overlay (step, mode, sim time)

## Tests

```bash
uv run pytest reels/tests
uv run python reels/tests/make_fixture.py   # rebuild the fixture sim from skip-morning-s-14
```
