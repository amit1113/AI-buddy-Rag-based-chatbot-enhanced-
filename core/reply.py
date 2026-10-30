"""What every tool returns, so the terminal now and the overlay UI later can show it the same way."""
from dataclasses import dataclass, field


@dataclass
class Reply:
    text: str
    sources: list = field(default_factory=list)  # [{"file", "page", "score"}]
    remember: bool = True   # store this exchange in conversation memory?
    end: bool = False       # tells the app to exit
    clear: bool = False     # tells the app to wipe the visible conversation
    tool: str = ""          # which tool produced this reply ("chat", "doc", "screen")
    routed_by: str = ""     # how it was chosen automatically ("rule", "llm", ...); empty if typed explicitly
