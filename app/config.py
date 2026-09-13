import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    with open(ROOT / "config.json", "r", encoding="utf-8") as f:
        return json.load(f)


CONFIG = load_config()

# api_key 支持环境变量覆盖，避免密钥进 git
_llm = CONFIG["llm"]
_llm["api_key"] = os.environ.get("ANCHOR_LLM_API_KEY", _llm["api_key"])
