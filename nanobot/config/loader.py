"""Configuration loading utilities."""

import json
from pathlib import Path

import pydantic
from loguru import logger

from nanobot.config.schema import Config

# Global variable to store current config path (for multi-instance support)
_current_config_path: Path | None = None


def set_config_path(path: Path) -> None:
    """Set the current config path (used to derive data directory)."""
    global _current_config_path
    _current_config_path = path


def get_config_path() -> Path:
    """Get the configuration file path."""
    if _current_config_path:
        return _current_config_path
    return Path.home() / ".nanobot" / "config.json"


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from file or create default.

    If a deployment preset plugin is installed, its defaults are
    deep-merged *under* the user's file values so explicit user
    choices always take priority.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Loaded configuration object.
    """
    path = config_path or get_config_path()
    preset_defaults = _get_preset_defaults()

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = _migrate_config(data)
            if preset_defaults:
                data = _deep_merge(preset_defaults, data)
            return Config.model_validate(data)
        except (json.JSONDecodeError, ValueError, pydantic.ValidationError) as e:
            logger.warning(f"Failed to load config from {path}: {e}")
            logger.warning("Using default configuration.")

    if preset_defaults:
        return Config.model_validate(preset_defaults)
    return Config()


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.
    """
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(mode="json", by_alias=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")

    # Run preset-specific migrations (if a preset plugin is installed).
    try:
        from nanobot.presets.registry import get_active_preset

        preset = get_active_preset()
        if preset:
            data = preset.migrate_config(data)
    except Exception as e:
        logger.debug("Preset migration skipped: {}", e)

    return data


def _get_preset_defaults() -> dict | None:
    """Return config overlay from the active deployment preset, or None."""
    try:
        from nanobot.presets.registry import get_active_preset

        preset = get_active_preset()
        return preset.config_defaults() if preset else None
    except Exception as e:
        logger.debug("Preset defaults skipped: {}", e)
        return None


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* on top of *base*. Override wins."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
