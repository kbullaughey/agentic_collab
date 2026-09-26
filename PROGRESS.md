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
