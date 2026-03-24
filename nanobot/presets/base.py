"""Base class for deployment preset plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rich.console import Console


class DeploymentPreset:
    """Base class for deployment presets.

    A deployment preset customises nanobot defaults for a specific
    environment (e.g. NVIDIA NIM, internal company gateway) without
    modifying core files.

    Subclass this, override the methods you need, then register via
    the ``nanobot.presets`` entry-point group in your ``pyproject.toml``.
    """

    name: str = ""
    display_name: str = ""

    def config_defaults(self) -> dict[str, Any]:
        """Return a config overlay dict (camelCase keys).

        Values are deep-merged *under* the user's ``config.json`` so the
        user's explicit choices always win.
        """
        return {}

    def migrate_config(self, data: dict[str, Any]) -> dict[str, Any]:
        """Optional config migration hook.

        Called during ``load_config`` after the built-in migrations.
        Return the (possibly modified) data dict.
        """
        return data

    def onboard_next_steps(
        self, console: Console, config_path: str, *, wizard: bool = False
    ) -> bool:
        """Print custom "next steps" after ``nanobot onboard``.

        Return ``True`` if you handled the message (suppresses the
        default text).  Return ``False`` to fall through to the default.
        """
        return False
