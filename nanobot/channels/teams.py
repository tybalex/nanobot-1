"""Microsoft Teams channel implementation using Bot Framework."""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base

try:
    from aiohttp import web
    from botbuilder.core import (
        BotFrameworkAdapter,
        BotFrameworkAdapterSettings,
        TurnContext,
    )
    from botbuilder.schema import Activity, ConversationReference

    _TEAMS_AVAILABLE = True
except ImportError:
    _TEAMS_AVAILABLE = False


class TeamsConfig(Base):
    """Microsoft Teams channel configuration."""

    enabled: bool = False
    app_id: str = ""
    app_password: str = ""
    tenant_id: str = ""
    port: int = 3978
    host: str = "0.0.0.0"
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
    group_policy: str = "mention"  # "mention" | "open"
    reply_in_thread: bool = True


class TeamsChannel(BaseChannel):
    """Microsoft Teams channel using Bot Framework."""

    name = "teams"
    display_name = "Microsoft Teams"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return TeamsConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if not _TEAMS_AVAILABLE:
            raise ImportError(
                "Teams dependencies not installed. Run: pip install nanobot-ai[teams]"
            )
        if isinstance(config, dict):
            config = TeamsConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: TeamsConfig = config
        self._adapter: BotFrameworkAdapter | None = None
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._bot_id: str | None = None
        self._bot_name: str | None = None
        # Conversation references for proactive messaging (persisted to disk)
        self._conv_refs: dict[str, dict] = {}
        self._conv_refs_path: Path | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """Start the Teams bot HTTP server."""
        if not self.config.app_id or not self.config.app_password:
            logger.error("Teams app_id/app_password not configured")
            return

        self._running = True

        settings = BotFrameworkAdapterSettings(
            app_id=self.config.app_id,
            app_password=self.config.app_password,
            channel_auth_tenant=self.config.tenant_id or None,
        )
        self._adapter = BotFrameworkAdapter(settings)
        self._bot_id = self.config.app_id

        # Load persisted conversation references
        self._load_conv_refs()

        # Set up aiohttp web server
        self._app = web.Application()
        self._app.router.add_post("/api/messages", self._handle_request)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.config.host, self.config.port)
        await site.start()

        logger.info(
            "Teams bot listening on http://{}:{}/api/messages",
            self.config.host,
            self.config.port,
        )

        # Keep running
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the Teams bot server."""
        self._running = False
        for task in self._typing_tasks.values():
            task.cancel()
        self._typing_tasks.clear()
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message to Teams."""
        if not self._adapter:
            logger.warning("Teams adapter not running")
            return

        teams_meta = msg.metadata.get("teams", {}) if msg.metadata else {}
        conv_ref_data = teams_meta.get("conversation_reference")

        # Try stored conversation reference for proactive messaging
        if not conv_ref_data:
            conv_ref_data = self._conv_refs.get(msg.chat_id)

        if not conv_ref_data:
            logger.warning("No conversation reference for chat_id={}", msg.chat_id)
            return

        conv_ref = ConversationReference().from_dict(conv_ref_data)

        # Stop typing when sending the final response
        if not (msg.metadata or {}).get("_progress"):
            self._stop_typing(msg.chat_id)

        try:
            async def _send_callback(turn_context: TurnContext):
                reply_to_id = teams_meta.get("reply_to_id")
                if reply_to_id and self.config.reply_in_thread:
                    activity = Activity(
                        type="message",
                        text=msg.content or " ",
                        conversation=turn_context.activity.conversation,
                        reply_to_id=reply_to_id,
                    )
                    await turn_context.send_activity(activity)
                else:
                    await turn_context.send_activity(msg.content or " ")

            await self._adapter.continue_conversation(
                conv_ref,
                _send_callback,
                self.config.app_id,
            )
        except Exception as e:
            logger.error("Error sending Teams message: {}", e)

    async def _handle_request(self, req: web.Request) -> web.Response:
        """Handle incoming HTTP requests from Bot Framework."""
        if "application/json" not in req.headers.get("Content-Type", ""):
            return web.Response(status=415)

        try:
            body = await req.json()
            activity = Activity().deserialize(body)
            auth_header = req.headers.get("Authorization", "")

            async def _turn_callback(turn_context: TurnContext):
                await self._on_message(turn_context)

            await self._adapter.process_activity(
                activity, auth_header, _turn_callback
            )
            return web.Response(status=201)
        except Exception as e:
            logger.error("Error handling Teams request: {}", e)
            return web.Response(status=500, text=str(e))

    async def _on_message(self, turn_context: TurnContext) -> None:
        """Process an incoming Teams message."""
        activity = turn_context.activity

        # Capture bot identity from the recipient field on first activity
        if not self._bot_name and activity.recipient:
            self._bot_id = activity.recipient.id
            self._bot_name = activity.recipient.name
            logger.info("Teams bot identity: {} ({})", self._bot_name, self._bot_id)

        # Only handle message activities
        if activity.type != "message":
            # Store conversation reference for any activity (enables proactive messaging)
            self._store_conv_ref(turn_context)
            return

        sender_id = activity.from_property.id if activity.from_property else ""
        sender_name = activity.from_property.name if activity.from_property else None
        text = activity.text or ""

        # Determine conversation type
        conv_type = self._get_conversation_type(activity)
        chat_id = activity.conversation.id if activity.conversation else ""

        if not sender_id or not chat_id:
            return

        # Store conversation reference for proactive messaging
        self._store_conv_ref(turn_context)

        # Check permissions
        if not self.is_allowed(sender_id):
            return

        # In channels/groups, check group policy
        if conv_type != "personal":
            if not self._should_respond(text, conv_type):
                return

        # Strip bot mention from text
        text = self._strip_bot_mention(text)

        if not text.strip():
            return

        # Send typing indicator while processing
        await self._start_typing(turn_context)

        # Build session key
        # Personal: teams:{conversation_id}
        # Channel/Group with reply: teams:{conversation_id}:{reply_to_id}
        # Channel/Group without reply: teams:{conversation_id}
        session_key = None
        reply_to_id = None
        if activity.reply_to_id and conv_type != "personal":
            reply_to_id = activity.reply_to_id
            session_key = f"teams:{chat_id}:{reply_to_id}"

        # Get conversation reference for outbound
        conv_ref = TurnContext.get_conversation_reference(activity)
        conv_ref_dict = conv_ref.as_dict()

        logger.debug(
            "Teams message: type={} sender={} ({}) chat={} text={}",
            conv_type,
            sender_id,
            sender_name,
            chat_id[:30],
            text[:80],
        )

        try:
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=text,
                sender_name=sender_name,
                metadata={
                    "teams": {
                        "conversation_reference": conv_ref_dict,
                        "conversation_type": conv_type,
                        "reply_to_id": reply_to_id or activity.id,
                    },
                },
                session_key=session_key,
            )
        except Exception:
            logger.exception("Error handling Teams message from {}", sender_id)

    def _get_conversation_type(self, activity: Activity) -> str:
        """Determine if conversation is personal, groupChat, or channel."""
        if activity.conversation:
            conv_type = getattr(activity.conversation, "conversation_type", None)
            if conv_type:
                return conv_type
            # Heuristic: personal conversations have shorter IDs
            conv_id = activity.conversation.id or ""
            if ";" not in conv_id and ":" not in conv_id:
                return "personal"
        return "channel"

    def _should_respond(self, text: str, conv_type: str) -> bool:
        """Check if the bot should respond based on group policy."""
        if self.config.group_policy == "open":
            return True
        if self.config.group_policy == "mention":
            # Teams wraps mentions as <at>BotName</at>
            if re.search(r"<at>[^<]*</at>", text):
                return True
            # Also check for plain @name (some clients don't use <at> tags)
            if self._bot_name and self._bot_name.lower() in text.lower():
                return True
            return False
        return False

    def _strip_bot_mention(self, text: str) -> str:
        """Remove bot @mention tags from message text."""
        # Teams format: <at>BotName</at>
        cleaned = re.sub(r"<at>[^<]*</at>\s*", "", text).strip()
        return cleaned or text

    def _store_conv_ref(self, turn_context: TurnContext) -> None:
        """Store conversation reference for proactive messaging."""
        activity = turn_context.activity
        conv_ref = TurnContext.get_conversation_reference(activity)
        chat_id = activity.conversation.id if activity.conversation else ""
        if chat_id:
            self._conv_refs[chat_id] = conv_ref.as_dict()
            self._save_conv_refs()

    def _load_conv_refs(self) -> None:
        """Load conversation references from disk."""
        self._conv_refs_path = Path.home() / ".nanobot" / "workspace" / "teams_references.json"
        if self._conv_refs_path.exists():
            try:
                self._conv_refs = json.loads(
                    self._conv_refs_path.read_text(encoding="utf-8")
                )
                logger.info("Loaded {} Teams conversation references", len(self._conv_refs))
            except Exception as e:
                logger.warning("Failed to load Teams references: {}", e)
                self._conv_refs = {}

    def _save_conv_refs(self) -> None:
        """Persist conversation references to disk."""
        if self._conv_refs_path:
            try:
                self._conv_refs_path.parent.mkdir(parents=True, exist_ok=True)
                self._conv_refs_path.write_text(
                    json.dumps(self._conv_refs, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception as e:
                logger.warning("Failed to save Teams references: {}", e)

    async def _start_typing(self, turn_context: TurnContext) -> None:
        """Start periodic typing indicator for a conversation."""
        chat_id = turn_context.activity.conversation.id if turn_context.activity.conversation else ""
        if not chat_id:
            return
        self._stop_typing(chat_id)

        # Store the conversation reference for typing
        conv_ref = TurnContext.get_conversation_reference(turn_context.activity)
        conv_ref_dict = conv_ref.as_dict()

        async def typing_loop() -> None:
            while self._running:
                try:
                    ref = ConversationReference().from_dict(conv_ref_dict)

                    async def _send_typing(ctx: TurnContext):
                        typing_activity = Activity(type="typing")
                        await ctx.send_activity(typing_activity)

                    await self._adapter.continue_conversation(
                        ref, _send_typing, self.config.app_id,
                    )
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    logger.debug("Teams typing indicator failed: {}", e)
                    return
                await asyncio.sleep(3)  # Teams typing indicator lasts ~3 seconds

        self._typing_tasks[chat_id] = asyncio.create_task(typing_loop())

    def _stop_typing(self, chat_id: str) -> None:
        """Stop typing indicator for a conversation."""
        task = self._typing_tasks.pop(chat_id, None)
        if task:
            task.cancel()
