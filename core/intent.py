"""Automatic tool choice: is a plain message chat, a question about the user's documents,
or a question about what is on their screen?

Strategy ("hybrid"): obvious cases are settled by cheap rules; everything else is decided by a
short LLM call. Which tools are even possible depends on the situation: documents must be added
and a screenshot must be attached. Typing /chat, /doc or /screen always overrides this."""
import json
import re
from dataclasses import dataclass

from . import config, llm

SCREEN_PATTERNS = [re.compile(p) for p in (
    r"\b(on|in|at)\s+(my|the|this)\s+(screen|window|tab|browser|page)\b",
    r"\b(this|that)\s+(page|screen|window|tab|website|site|webpage|error|dialog|popup|pop-up|code|"
    r"table|chart|graph|formula|image|picture|email|form|spreadsheet|sheet|slide|video|paragraph|"
    r"section|line|function|number|price|row|column|cell|button|menu|link)\b",
    r"\bwhat\s+(am\s+i|are\s+we)\s+(looking|seeing)\b",
    r"\bwhat\s+do\s+you\s+see\b",
    r"\bwhat('?s|\s+is)\s+(on\s+)?(my\s+)?screen\b",
    r"\b(shown|visible|displayed)\s+(here|above|below)\b",
    r"\b(take|have)\s+a\s+look\b",
    r"\blook\s+(at|into)\s+(my|this|the|that)\s+(?:[\w'-]+\s+){0,2}(screen|window|tab|browser|page|settings|app|desktop)\b",
    r"\b(my|the)\s+(active|current|open)\s+(tab|window|page|browser)\b",
    r"\b(active|current)\s+(tab|window|page)\b",
    r"\bmy\s+(browser|screen|desktop)\b",
)]

DOC_PATTERNS = [re.compile(p) for p in (
    r"\b(in|from|according\s+to|based\s+on)\s+(the|my|this|that)\s+(?:[\w-]+\s+){0,2}"
    r"(document|documents|doc|docs|pdf|pdfs|report|paper|invoice|bill|receipt|contract|notes)\b",
    r"\bmy\s+(?:[\w-]+\s+)?(documents|docs|pdfs|files|reports?|papers?)\b",
    r"\b(uploaded|added|indexed)\s+(documents?|files?|pdfs?)\b",
    r"\bwhat\s+(does|did)\s+the\s+(?:[\w-]+\s+)?(document|pdf|report|paper|invoice|bill|receipt|contract)\s+say\b",
    r"\b(which|what)\s+page\b",
)]

CLASSIFIER_SYSTEM = (
    "You route one user message to exactly one tool.\n"
    "- chat: general conversation or knowledge; needs no files and no screen.\n"
    "- doc: answer from the user's added documents (PDF files).\n"
    "- screen: the user wants you to look at their screen or at the window they are working in "
    "(a web page, an app, a settings window, an error message, code, a table...). The screenshot is "
    "taken only if you choose screen.\n"
    "Rules: choose only from the available tools. A short follow-up usually goes to the same tool as "
    "the previous message. Choose screen only if answering requires seeing what is on their screen, for "
    "example when they ask you to look at, check or read something on their computer, or refer to 'this "
    "page', 'this error' or 'here'. If it asks about content that would be in the user's documents, "
    "choose doc. Otherwise, including general knowledge questions, choose chat.\n"
    'Reply with JSON only, like {"tool": "chat"}.'
)


@dataclass
class Decision:
    tool: str
    method: str   # "only-option", "off", "rule", "llm" or "fallback"
    reason: str = ""


def candidate_tools(has_docs, has_screen):
    return ["chat"] + (["doc"] if has_docs else []) + (["screen"] if has_screen else [])


def rule_based(question, candidates):
    """A decision when the wording is unambiguous, otherwise None."""
    q = question.lower()
    screen_hit = "screen" in candidates and any(p.search(q) for p in SCREEN_PATTERNS)
    doc_hit = "doc" in candidates and any(p.search(q) for p in DOC_PATTERNS)
    if screen_hit and not doc_hit:
        return Decision("screen", "rule", "refers to something on the screen")
    if doc_hit and not screen_hit:
        return Decision("doc", "rule", "refers to your documents")
    return None


def fallback_tool(candidates, last_tool):
    """Used when nothing else decided. Stay with the previous tool (a follow-up probably continues it),
    otherwise plain chat. The screen is never a blind default: a screenshot only happens when a rule
    or the model says the question needs it."""
    return last_tool if last_tool in candidates else "chat"


def classify_with_llm(question, candidates, doc_names=(), screen_app="", last_tool=None, generate=None):
    """Ask the model which tool fits. Returns a tool name from candidates, or None if the answer
    could not be understood. Raises if the API call itself fails."""
    generate = generate or llm.generate
    lines = [f"Available tools: {', '.join(candidates)}"]
    if "doc" in candidates:
        lines.append("Documents added: " + (", ".join(doc_names) or "(unknown)"))
    if "screen" in candidates:
        lines.append(f"Screen: can be captured on request{f' (active window app: {screen_app})' if screen_app else ''}")
    lines.append(f"Previous tool used: {last_tool or 'none'}")
    lines.append(f"Message: {question}")
    text = generate("\n".join(lines), system=CLASSIFIER_SYSTEM, temperature=0).strip()

    match = re.search(r"\{.*?\}", text, re.S)
    tool = None
    if match:
        try:
            tool = str(json.loads(match.group(0)).get("tool", "")).strip().lower()
        except (ValueError, AttributeError):
            tool = None
    elif text.lower() in candidates:  # the model answered with the bare word
        tool = text.lower()
    return tool if tool in candidates else None


def choose_tool(question, *, has_docs, has_screen, doc_names=(), screen_app="", last_tool=None,
                mode=None, classify=None):
    """Pick the tool for a plain message. classify can be replaced (used by the evaluation scripts)."""
    mode = mode or config.AUTO_ROUTE
    candidates = candidate_tools(has_docs, has_screen)
    if len(candidates) == 1:
        return Decision("chat", "only-option", "no documents or screen available")
    if mode == "off":
        return Decision("chat", "off", "automatic routing is off; use /doc or /screen")

    if mode in ("rules", "hybrid"):
        decision = rule_based(question, candidates)
        if decision:
            return decision
        if mode == "rules":
            return Decision(fallback_tool(candidates, last_tool), "fallback", "no rule matched")

    classify = classify or classify_with_llm
    try:
        tool = classify(question, candidates, doc_names, screen_app, last_tool)
    except Exception as exc:  # routing must never block an answer
        return Decision(fallback_tool(candidates, last_tool), "fallback", f"classifier failed: {str(exc)[:80]}")
    if tool in candidates:
        return Decision(tool, "llm", "chosen by the model")
    return Decision(fallback_tool(candidates, last_tool), "fallback", "classifier gave no usable answer")
