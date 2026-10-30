"""Decides what a typed message means. Pure function with no side effects, so it is easy to test
and easy to replace with a smarter classifier in step 5."""
from dataclasses import dataclass

DEFAULT_TOOL = "chat"
TOOL_PREFIXES = {"/chat": "chat", "/doc": "doc", "/screen": "screen"}
COMMANDS = {"/help", "/list", "/add", "/remove", "/clear", "/quit", "/exit"}


@dataclass
class Route:
    kind: str  # "tool" or "command"
    name: str  # tool name ("chat", "doc", "screen") or command name ("add", "list", ...)
    text: str  # the question, or the argument of the command
    explicit: bool = False  # True when the user typed a /tool prefix


def route(message):
    message = message.strip()
    if not message.startswith("/"):
        return Route("tool", DEFAULT_TOOL, message, explicit=False)

    head, _, rest = message.partition(" ")
    head, rest = head.lower(), rest.strip()
    if head in TOOL_PREFIXES:
        return Route("tool", TOOL_PREFIXES[head], rest, explicit=True)
    if head in COMMANDS:
        return Route("command", head[1:], rest)
    return Route("command", "unknown", message)
