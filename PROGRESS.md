# Progress Log

## 2026-09-26 — Migrate conda → uv, .env config, gpt-6-luna

### Done
- `pyproject.toml`: runtime deps (openai 3.x, openai-cost-logger, pydantic, python-dotenv, numpy, paho-mqtt, Django 2.2, cors-headers, storages-redux/boto) plus `dev` and `analysis` dependency groups. `uv.lock` + `.python-version` (3.11). Removed `requirements.txt` (a frozen conda dump; many pins such as gensim 3.8, llama_cpp, gpt4all, Pillow 8.4 don't build on current macOS/Python).
- `reverie/backend_server/utils.py` is now committed and secret-free (removed from `.gitignore`). It loads `<repo>/.env` via python-dotenv (explicit path; `load_dotenv()` with no args searches from the *calling script's* directory, not cwd), holds `DEFAULT_OPENAI_CONFIG`, merges optional `openai_config.json`, and fills `model-key`/`embeddings-key` from `OPENAI_API_KEY` (or `AZURE_OPENAI_API_KEY`). `common.py` and `gpt_structure.py` import `openai_config` from it rather than reading the JSON via a cwd-relative path. Also added the MQTT settings `reverie.py` imports (defaults match `mqtt_gateway/config.py`).
- Default model `gpt-6-luna` ($0.10 in / $0.50 out per 1M tokens), embeddings `text-embedding-3-small`.
- `gpt_structure.py`: `GPT_request`/`GPT_structured_request` now build params via `sampling_kwargs()`. gpt-6-luna returns 400 for `max_tokens`, `temperature=0`, and `stop`; these are sent only when `"legacy-sampling-params": true`. Optional `"reasoning-effort"` (luna: none/low/medium/high/xhigh; NOT minimal) is applied to all chat calls. Those two functions now also call `log_cost()`. Previously they skipped the cost logger, so their spend didn't count toward `cost-upperbound`.
- Run scripts use `uv run python` in place of conda activation (`--conda_path`/`--env_name` removed). README updated.

### Verified
- `./run_backend_automatic.sh -o base_the_ville_isabella_maria_klaus -t test_1 -s 4 --ui None` → finished, no errors, ~$0.005, ~3 min. Plans/movements coherent.
- `./run_backend.sh` manual mode, `headless 2` → OK.
- `./run_frontend.sh` → `/`, `/simulator_home`, `/replay/<sim>/0/` return 200.

### Findings / recommendations
- `run_backend.sh` passes `--origin/--target`, but `reverie.py` ignores argv and prompts interactively (origin, target, MQTT y/N). Either add argparse to `reverie.py` or drop the args from the script.
- Auto-exec prints `Cost of 'test_1': 0` but a nonzero total, likely because the cost log is keyed by `experiment-name` (default `simulacra-test`), not the sim name.
- Dropping `stop` for reasoning models may change outputs of legacy prompts that relied on it for truncation; none failed in the short runs.
- `django-storages-redux` emits a deprecation warning; Django is held < 4.0 because `urls.py` uses `django.conf.urls.url`. Upgrading to Django 4.2 + `re_path` would be a small follow-up.
- `nlp/openai_convo_summary.py` still hardcodes a placeholder API key.

## 2026-09-26 — TUTORIAL.md

### Done
- Wrote `TUTORIAL.md`: architecture, step loop, cognitive modules, memory formats, map/blocks/remaps, LLM/prompt layer, input vs. output files, run modes, interviews, customization recipes, bundled scenarios, and a limitations list.

### Findings (from code reading; see TUTORIAL.md §16)
- `"block_remaps": {}` crashes `Maze` with `KeyError: 'sector'` (verified). `base_search_and_rescue/reverie/meta.json` has this. Fix: `.get(..., {})` in `maze.py` or use `null`.
- `commander_op` Commander Cody `scratch.json` uses `congnative`/`embodied`; the code reads `noncognitive`/`nonembodied`, so the flags are ignored.
- Live UI handshake looks broken: `home/main_script.html` sends positions as a GET body to `get_movements` and POSTs `{step, sim_code}` without `environment` to `send_environment`. The endpoints look swapped vs. upstream. Not browser-tested.
- MQTT topic mismatch: Django publishes `reverie/<sim>/environment`, gateway listens on `frontend/environment`.
- `extract_recency` gives the oldest node the highest recency (inherited from upstream).
- `retrieve()` calls `get_embedding` for every candidate memory each step despite the `a_mem.embeddings` cache.
- `maze_name` is effectively ignored (`utils.env_matrix` hard-codes `the_ville`). Several scratch knobs are loaded but unused. Memory `expiration` is never enforced. `daily_req` isn't regenerated after day 1. The plugin runner is commented out.
- Interviews: `call -- analysis <Name>` (answer is visible only in the debug dump) and `open_convo_session("analysis", direct=True, question=...)` (used by `survey.ipynb`).

### Recommendations
- Fix the two config bugs above (small).
- Add an `interview.py` CLI (questions file → CSV across checkpoints, no side effects).
- Cache embeddings in `retrieve()`; parameterize map paths by `maze_name`.

## 2026-09-26 — Embedding cache in `retrieve()`

### Done
- `persona/cognitive_modules/retrieve.py`: `retrieve()` now gets vectors from `a_mem.embeddings` through the new `get_node_embedding(persona, node)`. It falls back to one API call (and caches the result) if a key is missing. It previously called `get_embedding(node.description)` for the perceived event and every keyword-matched candidate on every step.
- Behavior change: similarity now compares `embedding_key` vectors (e.g. "serving coffee") rather than full event descriptions ("Isabella Rodriguez is serving coffee"). This matches how `new_retrieve` already scores relevance. Thoughts are unaffected (their key equals their description).

### Verified
- Offline, with `get_embedding` stubbed to count calls, on 4 agents from `skip-morning-s-14` with 8 perceived events each: 0 API calls, vs. 513 under the old code (256 for Isabella alone, who has 126 memories).
- `./run_backend_automatic.sh -o base_the_ville_isabella_maria_klaus -t embcache_test -s 4 --ui None`: no errors or fail-safes, sensible actions. Embedding calls fell from 157 to 30 and chat calls held at 41, vs. the earlier identical run. Test sim folders deleted afterwards.
