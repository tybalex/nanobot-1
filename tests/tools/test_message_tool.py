import pytest

from nanobot.agent.tools.message import MessageTool


@pytest.mark.asyncio
async def test_message_tool_returns_error_when_no_callback() -> None:
    tool = MessageTool()
    result = await tool.execute(content="test")
    assert result == "Error: Message sending not configured"


@pytest.mark.asyncio
async def test_message_tool_returns_error_when_no_target_context() -> None:
    from nanobot.agent.routing import tool_routing
    tool_routing.set(("", "", None))
    tool = MessageTool()
    result = await tool.execute(content="test")
    assert result == "Error: No target channel/chat specified"
