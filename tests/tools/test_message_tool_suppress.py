"""Test message tool suppress logic for final replies."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")


class TestMessageToolSuppressLogic:
    """Final reply suppressed only when message tool sends to the same target."""

    @pytest.mark.asyncio
    async def test_suppress_when_sent_to_same_target(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(
            id="call1", name="message",
            arguments={"content": "Hello", "channel": "feishu", "chat_id": "chat123"},
        )
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        sent: list[OutboundMessage] = []
        mt = loop.tools.get("message")
        if isinstance(mt, MessageTool):
            mt.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Send")
        result = await loop._process_message(msg)

        assert len(sent) == 1
        assert result is None  # suppressed

    @pytest.mark.asyncio
    async def test_not_suppress_when_sent_to_different_target(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(
            id="call1", name="message",
            arguments={"content": "Email content", "channel": "email", "chat_id": "user@example.com"},
        )
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="I've sent the email.", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        sent: list[OutboundMessage] = []
        mt = loop.tools.get("message")
        if isinstance(mt, MessageTool):
            mt.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Send email")
        result = await loop._process_message(msg)

        assert len(sent) == 1
        assert sent[0].channel == "email"
        assert result is not None  # not suppressed
        assert result.channel == "feishu"

    @pytest.mark.asyncio
    async def test_not_suppress_when_no_message_tool_used(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="Hello!", tool_calls=[]))
        loop.tools.get_definitions = MagicMock(return_value=[])

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Hi")
        result = await loop._process_message(msg)

        assert result is not None
        assert "Hello" in result.content

    async def test_progress_hides_internal_reasoning(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(
                content="Visible<think>hidden</think>",
                tool_calls=[tool_call],
                reasoning_content="secret reasoning",
                thinking_blocks=[{"signature": "sig", "thought": "secret thought"}],
            ),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        progress: list[tuple[str, bool]] = []

        async def on_progress(content: str, *, tool_hint: bool = False) -> None:
            progress.append((content, tool_hint))

        final_content, _, _ = await loop._run_agent_loop([], on_progress=on_progress)

        assert final_content == "Done"
        assert progress == [
            ("Visible", False),
            ('read_file("foo.txt")', True),
        ]


class TestMessageToolTurnTracking:

    def test_turn_state_tracks_sent(self) -> None:
        from nanobot.agent.routing import TurnState, tool_routing, turn_state
        tool_routing.set(("feishu", "chat1", None))
        state = TurnState()
        turn_state.set(state)
        assert not state.sent
        state.sent = True
        assert turn_state.get().sent

    def test_turn_state_resets_on_new_turn(self) -> None:
        from nanobot.agent.routing import TurnState, turn_state
        old = TurnState()
        old.sent = True
        turn_state.set(old)
        new = TurnState()
        turn_state.set(new)
        assert not turn_state.get().sent

    @pytest.mark.asyncio
    async def test_concurrent_tasks_isolated(self) -> None:
        """Two asyncio tasks with different routing don't interfere."""
        import asyncio
        from nanobot.agent.routing import TurnState, tool_routing, turn_state

        results: dict[str, tuple[str, str, bool]] = {}

        async def task_a():
            tool_routing.set(("slack", "chan_a", None))
            state = TurnState()
            turn_state.set(state)
            await asyncio.sleep(0.01)  # yield to let task_b run
            ch, cid, _ = tool_routing.get()
            state.sent = True
            results["a"] = (ch, cid, turn_state.get().sent)

        async def task_b():
            tool_routing.set(("teams", "chan_b", None))
            state = TurnState()
            turn_state.set(state)
            state.sent = True
            await asyncio.sleep(0.01)  # yield to let task_a run
            ch, cid, _ = tool_routing.get()
            results["b"] = (ch, cid, turn_state.get().sent)

        await asyncio.gather(
            asyncio.create_task(task_a()),
            asyncio.create_task(task_b()),
        )

        assert results["a"] == ("slack", "chan_a", True)
        assert results["b"] == ("teams", "chan_b", True)

    @pytest.mark.asyncio
    async def test_turn_state_visible_across_gather(self) -> None:
        """TurnState mutations in asyncio.gather child tasks are visible to parent."""
        import asyncio
        from nanobot.agent.routing import TurnState, turn_state

        state = TurnState()
        turn_state.set(state)

        async def child():
            turn_state.get().sent = True

        await asyncio.gather(asyncio.create_task(child()))
        assert state.sent is True
