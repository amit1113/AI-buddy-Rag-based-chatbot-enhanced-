"""The assistant core: routes a message, runs the right tool, keeps shared memory."""
from pathlib import Path

from . import config
from .intent import choose_tool
from .memory import ConversationMemory
from .reply import Reply
from .router import DEFAULT_TOOL, route

HELP_TEXT = """Just type a question: AI Buddy picks chat, your documents, or your screen for you.
To choose yourself, start with a command:
  /chat <question>     general chat
  /doc <question>      ask about the documents you added
  /screen <question>   ask about a window: you get a few seconds to switch to it
Other commands
  /add <path>          add a PDF, e.g. /add "C:\\Users\\you\\report.pdf"
  /list                show added documents
  /remove <file name>  remove a document
  /clear               forget this conversation
  /quit                exit"""


class Assistant:
    def __init__(self, tools, memory=None):
        """tools: {"chat": tool, "doc": tool, "screen": tool}; each has run(question, history) -> Reply."""
        self.tools = tools
        self.memory = memory or ConversationMemory(config.MEMORY_MESSAGES)
        self.last_tool = None

    def handle(self, message, screen_source=None):
        """screen_source: a window the assistant may look at (overlay app). It is only captured
        if the message ends up routed to the screen tool."""
        r = route(message)
        if not r.text and r.kind == "tool":
            return Reply(f"Usage: /{r.name} <your question>", remember=False)
        if r.kind == "command":
            return self._command(r.name, r.text)

        name, routed_by = r.name, ""
        if name == DEFAULT_TOOL and not r.explicit:
            decision = self._auto_route(r.text, screen_source)
            name, routed_by = decision.tool, decision.method
        reply = self._run_tool(name, r.text, screen_source)
        reply.tool = name
        reply.routed_by = routed_by if routed_by not in ("only-option", "off") else ""
        return reply

    # ---- routing ----
    def _document_names(self):
        docs = self.tools.get("doc")
        if docs is None or not hasattr(docs, "list_documents"):
            return []
        return list(docs.list_documents())

    def _auto_route(self, question, screen_source):
        doc_names = self._document_names()
        has_screen = screen_source is not None and screen_source.available
        screen_app = screen_source.app if has_screen else ""
        return choose_tool(
            question,
            has_docs=bool(doc_names),
            has_screen=has_screen,
            doc_names=doc_names,
            screen_app=screen_app,
            last_tool=self.last_tool,
        )

    # ---- tools ----
    def _run_tool(self, name, question, screen_source=None):
        tool = self.tools.get(name)
        if tool is None:
            return Reply(f"The '{name}' tool is not available.", remember=False)
        if name == "screen" and screen_source is not None and screen_source.available:
            context = screen_source.capture()  # the screenshot is taken now, not before
            reply = tool.run(question, self.memory.messages(), context=context)
        else:
            reply = tool.run(question, self.memory.messages())
        if reply.remember:  # only store successful exchanges
            self.memory.add("user", question)
            self.memory.add("assistant", reply.text)
            self.last_tool = name
        return reply

    # ---- commands ----
    def _command(self, name, argument):
        if name == "help":
            return Reply(HELP_TEXT, remember=False)
        if name in ("quit", "exit"):
            return Reply("Bye!", remember=False, end=True)
        if name == "clear":
            self.memory.clear()
            self.last_tool = None
            return Reply("Conversation cleared.", remember=False, clear=True)
        if name == "unknown":
            return Reply("Unknown command. Type /help to see what is available.", remember=False)

        docs = self.tools.get("doc")
        if docs is None:
            return Reply("The documents tool is not available.", remember=False)

        if name == "list":
            documents = docs.list_documents()
            if not documents:
                return Reply("No documents yet. Add one with /add <path-to-pdf>.", remember=False)
            lines = [f"  {file} ({count} chunks)" for file, count in documents.items()]
            return Reply("Documents:\n" + "\n".join(lines), remember=False)

        if name == "remove":
            if not argument:
                return Reply("Usage: /remove <file name>", remember=False)
            removed = docs.remove(argument.strip('"').strip("'"))
            return Reply("Removed." if removed else "No document with that name. Use /list.", remember=False)

        if name == "add":
            if not argument:
                return Reply("Usage: /add <path-to-pdf>", remember=False)
            path = Path(argument.strip('"').strip("'")).expanduser()
            if not path.exists():
                return Reply(f"I can't find that file: {path}", remember=False)
            if path.suffix.lower() != ".pdf":
                return Reply("Only PDF files are supported for now.", remember=False)
            try:
                count = docs.add_pdf(path)
            except ValueError as exc:  # e.g. scanned PDF with no text
                return Reply(str(exc), remember=False)
            return Reply(f"Added {path.name} ({count} chunks).", remember=False)

        return Reply("Unknown command. Type /help.", remember=False)
