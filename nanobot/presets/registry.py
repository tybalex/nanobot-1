"""Discovery for deployment preset plugins."""

from __future__ import annotations

from functools import lru_cache

from loguru import logger

from nanobot.presets.base import DeploymentPreset

_ENTRY_POINT_GROUP = "nanobot.presets"


@lru_cache(maxsize=1)
def _discover_presets() -> list[DeploymentPreset]:
    """Discover all installed deployment presets via entry_points."""
    from importlib.metadata import entry_points

    presets: list[DeploymentPreset] = []
    for ep in entry_points(group=_ENTRY_POINT_GROUP):
        try:
            cls = ep.load()
            if isinstance(cls, type) and issubclass(cls, DeploymentPreset):
                presets.append(cls())
            elif isinstance(cls, DeploymentPreset):
                presets.append(cls)
            else:
                logger.warning("Preset entry '{}' is not a DeploymentPreset subclass", ep.name)
        except Exception as e:
            logger.warning("Failed to load preset plugin '{}': {}", ep.name, e)
    return presets


def get_active_preset() -> DeploymentPreset | None:
    """Return the active deployment preset (first discovered), or None."""
    presets = _discover_presets()
    if len(presets) > 1:
        names = ", ".join(p.name or "unnamed" for p in presets)
        logger.warning("Multiple deployment presets installed ({}); using first", names)
    return presets[0] if presets else None
