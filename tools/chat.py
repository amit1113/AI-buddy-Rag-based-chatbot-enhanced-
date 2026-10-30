"""General chat tool: plain LLM answer with the shared conversation history."""
from core import llm
from core.reply import Reply

SYSTEM_PROMPT = (
    "You are AI Buddy, a friendly and concise assistant. Answer directly. "
    "If you are not sure about something, say so instead of guessing."
)


class ChatTool:
    def run(self, question, history):
        text = llm.generate(question, system=SYSTEM_PROMPT, history=history)
        return Reply(text.strip() or "I didn't get a response from the model. Please try again.")
