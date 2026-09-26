"""
File: utils.py
Description: Runtime settings for the backend simulation server.

Secrets are never stored here. API keys are read from environment variables,
which are loaded from the `.env` file at the repository root (if present).
Non-secret LLM settings (model, costs, ...) have defaults below and can be
overridden with an optional `openai_config.json` at the repository root.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

# Existing environment variables take precedence over values in .env.
load_dotenv(REPO_ROOT / ".env")

# ============================================================================
# LLM configuration
# ============================================================================

DEFAULT_OPENAI_CONFIG = {
  "client": "openai",
  "model": "gpt-6-luna",
  # Costs are in USD per million tokens.
  "model-costs": {
    "input": 0.10,
    "output": 0.50,
  },
  # Newer reasoning models (gpt-5.x, gpt-6.x) reject `max_tokens`,
  # non-default `temperature`, and `stop`. Set to true for older models
  # (e.g. gpt-4o-mini) to send the legacy sampling parameters.
  "legacy-sampling-params": False,
  # Optional: "none", "low", "medium", "high", "xhigh" (gpt-6-luna). None uses the model default.
  "reasoning-effort": None,
  "embeddings-client": "openai",
  "embeddings": "text-embedding-3-small",
  "embeddings-costs": {
    "input": 0.02,
    "output": 0.0,
  },
  "experiment-name": "simulacra-test",
  "cost-upperbound": 10,
}

# Environment variables that supply API keys when not set in the JSON config.
_KEY_ENV_VARS = {
  "openai": "OPENAI_API_KEY",
  "azure": "AZURE_OPENAI_API_KEY",
}


def load_openai_config(config_path: Path = REPO_ROOT / "openai_config.json") -> dict:
  """Build the LLM config from defaults, `openai_config.json`, and env vars."""
  config = json.loads(json.dumps(DEFAULT_OPENAI_CONFIG))
  if config_path.exists():
    with open(config_path, "r") as f:
      config.update(json.load(f))

  for key_field, client_field in (
    ("model-key", "client"),
    ("embeddings-key", "embeddings-client"),
  ):
    if not config.get(key_field):
      env_var = _KEY_ENV_VARS.get(config[client_field], "OPENAI_API_KEY")
      config[key_field] = os.getenv(env_var, "")
      if not config[key_field]:
        raise RuntimeError(
          f"No API key for '{key_field}'. Set {env_var} in {REPO_ROOT / '.env'} "
          "or in your environment."
        )
  return config


openai_config = load_openai_config()
openai_api_key = openai_config["model-key"]
key_owner = os.getenv("KEY_OWNER", "")

use_openai = True
# If you're not using OpenAI, define api_model
api_model = ""

# ============================================================================
# Paths (relative to reverie/backend_server, where the backend is launched)
# ============================================================================

maze_assets_loc = "../../environment/frontend_server/static_dirs/assets"
env_matrix = f"{maze_assets_loc}/the_ville/matrix"
env_visuals = f"{maze_assets_loc}/the_ville/visuals"

fs_storage = "../../environment/frontend_server/storage"
fs_temp_storage = "../../environment/frontend_server/temp_storage"

collision_block_id = "32125"

# Verbose
debug = True

# ============================================================================
# MQTT (only used when running with --mqtt); topics match mqtt_gateway/config.py
# ============================================================================

mqtt_host = os.getenv("MQTT_BROKER_HOST", "localhost")
mqtt_port = int(os.getenv("MQTT_BROKER_PORT", 1883))
mqtt_client_id = os.getenv("MQTT_CLIENT_ID", "reverie_backend")
mqtt_movement_topic = "backend/movement"
mqtt_environment_topic = "gateway/environment"
