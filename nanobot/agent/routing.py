"""Task-local routing context for tool execution.

When multiple sessions process concurrently (each in its own asyncio Task),
tools need to know which channel/chat they're operating on behalf of.  Using
module-level ``ContextVar`` instances ensures each Task sees its own values
without races on shared instance variables.
"""

from contextvars import ContextVar


# (channel, chat_id, message_id) for the current processing task.
# Set by AgentLoop._set_tool_context(); read by MessageTool, SpawnTool, CronTool.
tool_routing: ContextVar[tuple[str, str, str | None]] = ContextVar(
    "tool_routing", default=("cli", "direct", None)
)


class TurnState:
    """Mutable container for per-turn state shared across tool-call subtasks.

    asyncio.gather() wraps coroutines in child Tasks that inherit ContextVar
    values by reference.  A plain ``ContextVar[bool]`` would be copied (so
    mutations in a child Task are invisible to the parent).  By storing a
    *mutable object* in the ContextVar, child tasks mutate the same instance
    the parent sees.
    """
    __slots__ = ("sent",)

    def __init__(self) -> None:
        self.sent: bool = False


# Per-turn mutable state. Set to a fresh TurnState at the start of each turn;
# tools mutate the same instance during that turn.
turn_state: ContextVar[TurnState] = ContextVar("turn_state")
