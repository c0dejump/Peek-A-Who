"""
Config manager — reads/writes the project .env file and detects Ollama models.
"""
from __future__ import annotations

import os
import re
from typing import Optional

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
_ENV_PATH = os.path.abspath(_ENV_PATH)

PROVIDERS = {
    "ollama":    {"label": "Ollama",    "free": True,  "local": True,  "key_var": None,              "key_hint": ""},
    "groq":      {"label": "Groq",      "free": True,  "local": False, "key_var": "GROQ_API_KEY",    "key_hint": "gsk_..."},
    "gemini":    {"label": "Gemini",    "free": True,  "local": False, "key_var": "GEMINI_API_KEY",  "key_hint": "AIza..."},
    "anthropic": {"label": "Anthropic", "free": False, "local": False, "key_var": "ANTHROPIC_API_KEY","key_hint": "sk-ant-..."},
    "openai":    {"label": "OpenAI",    "free": False, "local": False, "key_var": "OPENAI_API_KEY",  "key_hint": "sk-..."},
}

DEFAULT_MODELS = {
    "ollama":    ["llama3.1", "llama3.2", "llama3.3", "mistral", "qwen2.5:7b", "qwen2.5:14b", "deepseek-r1:8b"],
    "groq":      ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"],
    "gemini":    ["gemini-2.0-flash-exp", "gemini-1.5-flash", "gemini-1.5-pro"],
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5-20251001"],
    "openai":    ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
}

OTHER_KEYS = ["HIBP_API_KEY", "PAPPERS_API_KEY", "TRUECALLER_TOKEN",
              "TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_PHONE"]


def read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not os.path.exists(_ENV_PATH):
        return env
    with open(_ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
    return env


def write_env(updates: dict[str, str]) -> None:
    lines: list[str] = []
    written: set[str] = set()

    if os.path.exists(_ENV_PATH):
        with open(_ENV_PATH) as f:
            raw = f.readlines()
        for line in raw:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                if k in updates:
                    # preserve comments on same line if any
                    lines.append(f"{k}={updates[k]}\n")
                    written.add(k)
                    continue
            lines.append(line)

    for k, v in updates.items():
        if k not in written:
            lines.append(f"{k}={v}\n")

    os.makedirs(os.path.dirname(_ENV_PATH), exist_ok=True)
    with open(_ENV_PATH, "w") as f:
        f.writelines(lines)

    # Reload into os.environ immediately
    from dotenv import load_dotenv
    load_dotenv(_ENV_PATH, override=True)


def get_current_config() -> dict:
    env = read_env()
    backend = env.get("LLM_BACKEND", "ollama/llama3.1")

    provider = "ollama"
    model = "llama3.1"
    if "/" in backend:
        provider, model = backend.split("/", 1)

    result = {
        "provider":   provider,
        "model":      model,
        "backend":    backend,
        "ollama_url": env.get("OLLAMA_API_BASE", "http://localhost:11434"),
        "other_keys": {k: env.get(k, "") for k in OTHER_KEYS},
    }

    for prov, meta in PROVIDERS.items():
        key_var = meta["key_var"]
        result[f"{prov}_key"] = env.get(key_var, "") if key_var else ""

    return result


def save_config(form: dict) -> None:
    provider = form.get("provider", "ollama")
    model    = form.get("model", "").strip()
    updates  = {"LLM_BACKEND": f"{provider}/{model}"}

    # provider API key
    key_var = PROVIDERS.get(provider, {}).get("key_var")
    if key_var:
        key_val = form.get("api_key", "").strip()
        if key_val:
            updates[key_var] = key_val

    # Ollama base URL
    if provider == "ollama":
        ollama_url = form.get("ollama_url", "http://localhost:11434").strip()
        updates["OLLAMA_API_BASE"] = ollama_url

    # Optional tool keys
    for k in OTHER_KEYS:
        val = form.get(k, "").strip()
        if val:
            updates[k] = val

    write_env(updates)


def get_ollama_models(base_url: str = "http://localhost:11434") -> tuple[bool, list[str]]:
    """Returns (is_running, model_list)."""
    try:
        import requests
        r = requests.get(f"{base_url}/api/tags", timeout=2)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            return True, models or DEFAULT_MODELS["ollama"]
    except Exception:
        pass
    return False, []
