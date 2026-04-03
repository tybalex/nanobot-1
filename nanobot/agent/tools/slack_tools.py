"""Slack tools for reading channel history, threads, and listing channels."""

from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


class SlackListChannelsTool(Tool):
    """List Slack channels the bot is a member of."""

    def __init__(self, bot_token: str):
        self._bot_token = bot_token

    @property
    def name(self) -> str:
        return "slack_list_channels"

    @property
    def description(self) -> str:
        return (
            "List Slack channels the bot is a member of. "
            "Returns channel names and IDs. Use this to discover channels "
            "before reading their history."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max channels to return (default 50, max 200)",
                },
            },
        }

    async def execute(self, limit: int = 50, **kwargs: Any) -> str:
        from slack_sdk.web.async_client import AsyncWebClient

        client = AsyncWebClient(token=self._bot_token)
        try:
            result = await client.conversations_list(
                types="public_channel,private_channel",
                limit=min(limit, 200),
            )
            channels = result.get("channels", [])
            if not channels:
                return "No channels found."

            lines = []
            for ch in channels:
                name = ch.get("name", "unknown")
                cid = ch.get("id", "")
                purpose = (ch.get("purpose") or {}).get("value", "")
                member = "member" if ch.get("is_member") else "not member"
                line = f"- #{name} ({cid}) [{member}]"
                if purpose:
                    line += f" — {purpose[:80]}"
                lines.append(line)
            return f"Found {len(channels)} channels:\n" + "\n".join(lines)
        except Exception as e:
            return f"Error listing channels: {e}"


class SlackReadHistoryTool(Tool):
    """Read recent message history from a Slack channel."""

    def __init__(self, bot_token: str):
        self._bot_token = bot_token

    @property
    def name(self) -> str:
        return "slack_read_history"

    @property
    def description(self) -> str:
        return (
            "Read recent messages from a Slack channel. "
            "Requires the channel ID (use slack_list_channels to find it). "
            "Returns messages in chronological order."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "Slack channel ID (e.g. C0123ABCDEF)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of messages to return (default 20, max 100)",
                },
            },
            "required": ["channel_id"],
        }

    async def execute(self, channel_id: str, limit: int = 20, **kwargs: Any) -> str:
        from slack_sdk.web.async_client import AsyncWebClient

        client = AsyncWebClient(token=self._bot_token)
        try:
            result = await client.conversations_history(
                channel=channel_id,
                limit=min(limit, 100),
            )
            messages = result.get("messages", [])
            if not messages:
                return f"No messages found in {channel_id}."

            # Messages come newest-first, reverse for chronological order
            messages.reverse()

            # Resolve user IDs to names (best effort, cached per call)
            user_cache: dict[str, str] = {}

            async def resolve_user(uid: str) -> str:
                if uid in user_cache:
                    return user_cache[uid]
                try:
                    info = await client.users_info(user=uid)
                    name = info["user"]["real_name"] or info["user"]["name"]
                    user_cache[uid] = name
                    return name
                except Exception:
                    user_cache[uid] = uid
                    return uid

            lines = []
            for msg in messages:
                user = msg.get("user", "unknown")
                text = msg.get("text", "")
                ts = msg.get("ts", "")

                # Convert timestamp to readable format
                try:
                    from datetime import datetime
                    dt = datetime.fromtimestamp(float(ts))
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                except (ValueError, OSError):
                    time_str = ts

                user_name = await resolve_user(user)
                thread_count = msg.get("reply_count", 0)
                thread_info = f" [{thread_count} replies]" if thread_count else ""
                lines.append(f"[{time_str}] {user_name}: {text}{thread_info}")

            return f"Last {len(messages)} messages from {channel_id}:\n" + "\n".join(lines)
        except Exception as e:
            return f"Error reading history: {e}"


class SlackReadThreadTool(Tool):
    """Read a full Slack thread."""

    def __init__(self, bot_token: str):
        self._bot_token = bot_token

    @property
    def name(self) -> str:
        return "slack_read_thread"

    @property
    def description(self) -> str:
        return (
            "Read all replies in a Slack thread. "
            "Requires the channel ID and the thread timestamp (ts) of the parent message. "
            "Use slack_read_history first to find threads."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "Slack channel ID",
                },
                "thread_ts": {
                    "type": "string",
                    "description": "Thread timestamp (ts) of the parent message",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max replies to return (default 50, max 200)",
                },
            },
            "required": ["channel_id", "thread_ts"],
        }

    async def execute(self, channel_id: str, thread_ts: str, limit: int = 50, **kwargs: Any) -> str:
        from slack_sdk.web.async_client import AsyncWebClient

        client = AsyncWebClient(token=self._bot_token)
        try:
            result = await client.conversations_replies(
                channel=channel_id,
                ts=thread_ts,
                limit=min(limit, 200),
            )
            messages = result.get("messages", [])
            if not messages:
                return f"No messages found in thread {thread_ts}."

            user_cache: dict[str, str] = {}

            async def resolve_user(uid: str) -> str:
                if uid in user_cache:
                    return user_cache[uid]
                try:
                    info = await client.users_info(user=uid)
                    name = info["user"]["real_name"] or info["user"]["name"]
                    user_cache[uid] = name
                    return name
                except Exception:
                    user_cache[uid] = uid
                    return uid

            lines = []
            for msg in messages:
                user = msg.get("user", "unknown")
                text = msg.get("text", "")
                ts = msg.get("ts", "")

                try:
                    from datetime import datetime
                    dt = datetime.fromtimestamp(float(ts))
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                except (ValueError, OSError):
                    time_str = ts

                user_name = await resolve_user(user)
                lines.append(f"[{time_str}] {user_name}: {text}")

            return f"Thread ({len(messages)} messages):\n" + "\n".join(lines)
        except Exception as e:
            return f"Error reading thread: {e}"
