"""
Jarvis Configuration Loader
============================
Loads jarvis.yaml and provides typed access to all settings.
Handles path expansion, defaults, and environment overrides.
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("jarvis.config")

# Project root: directory containing jarvis.yaml
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = PROJECT_ROOT / "jarvis.yaml"

# Singleton config instance
_config: Optional[dict] = None


def _expand_path(value: str) -> str:
    """Expand ~ and environment variables in path strings."""
    return os.path.expandvars(os.path.expanduser(value))


def _resolve_paths(data: dict, keys_with_paths: set[str]) -> dict:
    """Recursively resolve path-like values in config dict."""
    resolved = {}
    for key, value in data.items():
        if isinstance(value, dict):
            resolved[key] = _resolve_paths(value, keys_with_paths)
        elif isinstance(value, str) and key in keys_with_paths:
            resolved[key] = _expand_path(value)
        else:
            resolved[key] = value
    return resolved


# Keys whose string values represent filesystem paths
_PATH_KEYS = {
    "db_path", "voiceprint_path", "workflows_dir",
    "file", "system_prompt_file",
}


def load_config(config_path: Optional[Path] = None) -> dict:
    """
    Load and return the Jarvis configuration dictionary.
    
    Results are cached — subsequent calls return the same dict
    unless force_reload() is called.
    """
    global _config

    if _config is not None:
        return _config

    path = config_path or CONFIG_FILE

    if not path.exists():
        logger.warning("Config file not found at %s — using defaults", path)
        _config = _defaults()
        return _config

    with open(path, "r") as f:
        raw = yaml.safe_load(f) or {}

    # Merge with defaults so missing keys don't crash anything
    merged = _deep_merge(_defaults(), raw)

    # Expand ~ in path values
    _config = _resolve_paths(merged, _PATH_KEYS)

    # Ensure critical directories exist
    _ensure_data_dirs(_config)

    logger.info("Configuration loaded from %s", path)
    return _config


def force_reload(config_path: Optional[Path] = None) -> dict:
    """Force reload config from disk."""
    global _config
    _config = None
    return load_config(config_path)


def get(section: str, key: str = None, default: Any = None) -> Any:
    """
    Get a config value.
    
    Usage:
        get("llm", "model")        → "mistral:7b"
        get("audio")               → entire audio section dict
        get("llm", "missing", 42)  → 42
    """
    cfg = load_config()
    section_data = cfg.get(section, {})

    if key is None:
        return section_data if section_data else default

    if isinstance(section_data, dict):
        return section_data.get(key, default)

    return default


def _ensure_data_dirs(cfg: dict):
    """Create data directories if they don't exist."""
    dirs_to_create = [
        Path(cfg.get("memory", {}).get("db_path", "")).parent,
        Path(cfg.get("logging", {}).get("file", "")).parent,
        Path(cfg.get("automation", {}).get("workflows_dir", "")),
    ]

    for d in dirs_to_create:
        if str(d) and str(d) != ".":
            d.mkdir(parents=True, exist_ok=True)


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base. Override wins on conflicts."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _defaults() -> dict:
    """Hardcoded defaults — safety net if jarvis.yaml is missing."""
    return {
        "assistant": {
            "name": "Jarvis",
            "wake_word": "jarvis",
            "language": "en",
            "follow_up_timeout": 12,
            "command_timeout": 30,
        },
        "audio": {
            "device_index": None,
            "sample_rate": 16000,
            "channels": 1,
            "chunk_size": 1280,
            "energy_threshold": 300,
            "ambient_adjust_duration": 0.5,
        },
        "wake_word": {
            "engine": "openwakeword",
            "model": "hey_jarvis",
            "sensitivity": 0.6,
            "cooldown": 2.0,
        },
        "stt": {
            "engine": "faster-whisper",
            "model_size": "small",
            "language": "en",
            "fallback": "google",
            "fallback_language": "en-IN",
            "vad_silence_duration": 1.5,
            "max_recording_duration": 15,
        },
        "tts": {
            "engine": "piper",
            "voice": "en_IN-cmu_indic_kan-medium",
            "fallback": "espeak",
            "rate": 1.0,
            "output_device": None,
        },
        "llm": {
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model": "mistral:7b",
            "temperature": 0.3,
            "max_tokens": 512,
            "timeout": 30,
            "system_prompt_file": None,
        },
        "memory": {
            "db_path": "~/.local/share/jarvis/memory.db",
            "max_interactions": 10000,
            "context_window": 10,
            "preference_decay_days": 90,
        },
        "security": {
            "voice_auth_enabled": True,
            "voiceprint_path": "~/.local/share/jarvis/voiceprint.npy",
            "auth_threshold": 0.55,
            "sensitive_actions": [
                "file.delete", "file.write",
                "system.shutdown", "system.reboot", "system.sudo",
                "process.kill", "network.toggle",
            ],
        },
        "ui": {
            "enabled": True,
            "gnome_extension": True,
            "overlay": False,
            "position": "top-right",
            "margin_x": 20,
            "margin_y": 20,
            "opacity": 0.92,
            "width": 200,
            "height": 60,
            "animations": True,
        },
        "web": {
            "search_engine": "duckduckgo",
            "max_results": 5,
            "cache_ttl": 3600,
            "user_agent": "Jarvis/1.0",
        },
        "automation": {
            "workflows_dir": "~/.local/share/jarvis/workflows",
            "max_concurrent_steps": 3,
        },
        "logging": {
            "level": "INFO",
            "file": "~/.local/share/jarvis/jarvis.log",
            "max_size_mb": 10,
            "backup_count": 3,
        },
    }