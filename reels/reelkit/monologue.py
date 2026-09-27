"""Stage 3: generate monologue text for monologue beats with the configured LLM.

Keys and default model come from the backend's config (`.env` and optional
`openai_config.json`, via reverie/backend_server/utils.load_openai_config).
The reel config can override the model with `prompts.model`,
`prompts.reasoning_effort` and `prompts.model_costs`.
"""
import json
import re
import sys
import time
from datetime import datetime

from .config import REPO_ROOT, write_json

MIN_WORDS, MAX_WORDS = 10, 80


def _openai_setup():
  sys.path.insert(0, str(REPO_ROOT / "reverie" / "backend_server"))
  from openai import OpenAI

  from utils import load_openai_config
  cfg = load_openai_config()
  if cfg["client"] != "openai":
    raise SystemExit("reel monologue generation only supports the 'openai' client for now")
  return OpenAI(api_key=cfg["model-key"]), cfg


def clean_text(text):
  text = (text or "").strip()
  if len(text) >= 2 and text[0] in "\"'“" and text[-1] in "\"'”":
    text = text[1:-1].strip()
  return re.sub(r"\s+", " ", text)


def generate(cfg, beats, paths, only=None, redo=False, dry_run=False):
  todo = [b for b in beats["beats"] if b["type"] == "monologue"
          and (not only or b["id"] in only) and (redo or not b.get("text"))]
  if not todo:
    print("nothing to generate (use --redo to regenerate existing text)")
    return
  if dry_run:
    for b in todo:
      print(f"would generate {b['id']} ({b['trigger']}, prompt {b['prompt_version']}, {len(b['prompt'])} chars)")
    return

  client, ocfg = _openai_setup()
  pcfg = cfg["prompts"]
  model = pcfg.get("model") or ocfg["model"]
  costs = pcfg.get("model_costs") or ocfg["model-costs"]
  effort = pcfg.get("reasoning_effort", ocfg.get("reasoning-effort"))
  kwargs = {"reasoning_effort": effort} if effort else {}

  cost_path = paths["dir"] / "cost.json"
  log = json.loads(cost_path.read_text()) if cost_path.exists() else {"total_usd": 0.0, "calls": []}
  for b in todo:
    t0 = time.time()
    resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": b["prompt"]}], **kwargs)
    text = clean_text(resp.choices[0].message.content)
    usage = resp.usage
    usd = (usage.prompt_tokens * costs["input"] + usage.completion_tokens * costs["output"]) / 1e6
    n_words = len(text.split())
    b["text"] = text
    b["text_meta"] = {
      "model": model, "prompt_version": b["prompt_version"], "prompt_hash": b["prompt_hash"],
      "generated_at": datetime.now().isoformat(timespec="seconds"),
      "tokens_in": usage.prompt_tokens, "tokens_out": usage.completion_tokens, "usd": round(usd, 6),
    }
    log["calls"].append({"beat": b["id"], "model": model, "usd": round(usd, 6), "at": b["text_meta"]["generated_at"]})
    log["total_usd"] = round(log["total_usd"] + usd, 6)
    flag = "" if MIN_WORDS <= n_words <= MAX_WORDS else f"  WARNING: {n_words} words"
    print(f"{b['id']} ({time.time() - t0:.1f}s, ${usd:.5f}): {text}{flag}")
    # Save after every beat so an interrupted run keeps its progress.
    write_json(paths["beats"], beats)
    write_json(cost_path, log)
  print(f"total spent on this reel so far: ${log['total_usd']:.4f}")
