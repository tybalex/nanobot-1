"""NVIDIA NIM deployment preset."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.presets.base import DeploymentPreset

if TYPE_CHECKING:
    from rich.console import Console


class NvidiaPreset(DeploymentPreset):
    """Preset for NVIDIA NIM / Inference API deployments."""

    name = "nvidia"
    display_name = "NVIDIA NIM"

    def config_defaults(self) -> dict[str, Any]:
        return {
            "agents": {
                "defaults": {
                    "model": "aws/anthropic/bedrock-claude-sonnet-4-6",
                    "provider": "custom",
                    "maxToolIterations": 100,
                }
            },
            "providers": {
                "custom": {
                    "apiBase": "https://inference-api.nvidia.com",
                }
            },
        }

    def migrate_config(self, data: dict[str, Any]) -> dict[str, Any]:
        # Drop deprecated memoryWindow — it was never used at runtime.
        agents = data.get("agents", {})
        defaults = agents.get("defaults", {})
        defaults.pop("memoryWindow", None)
        defaults.pop("memory_window", None)
        return data

    def onboard_next_steps(
        self, console: Console, config_path: str, *, wizard: bool = False
    ) -> bool:
        console.print("  1. Set your NVIDIA API key (choose one):")
        console.print(
            "     [bold]Option A[/bold] — config file: add to "
            f"[cyan]{config_path}[/cyan]:"
        )
        console.print(
            '       [dim]{ "providers": { "custom": '
            '{ "apiKey": "your-nvapikey" } } }[/dim]'
        )
        console.print("     [bold]Option B[/bold] — environment variable:")
        console.print(
            '       [cyan]export NANOBOT_PROVIDERS__CUSTOM__API_KEY='
            '"your-nvapikey"[/cyan]'
        )
        console.print(
            '  2. Chat: [cyan]nanobot agent -m "Hello!"[/cyan]'
        )
        console.print("  3. Switch model (optional):")
        console.print(
            "     Default: [cyan]aws/anthropic/bedrock-claude-sonnet-4-6[/cyan]"
        )
        console.print(
            "     Also available: [cyan]aws/anthropic/claude-opus-4-5[/cyan]"
        )
        console.print(
            '     Set in config: [dim]{ "agents": { "defaults": '
            '{ "model": "aws/anthropic/claude-opus-4-5" } } }[/dim]'
        )
        return True
