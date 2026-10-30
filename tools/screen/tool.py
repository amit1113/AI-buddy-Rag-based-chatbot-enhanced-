"""Screen tool: look at the window the user is working in and answer a question about it."""
import time

from core import config, llm
from core.reply import Reply
from .capture import capture_active_window
from .context import ScreenContext, is_blocked, take_snapshot
from .window import get_active_window

SYSTEM_PROMPT = (
    "You are AI Buddy. The user shares a screenshot of the window they are looking at and asks "
    "about it. Answer from what is visible. If the answer is not visible in the screenshot, say so "
    "plainly instead of guessing. Be concise and practical."
)


class ScreenTool:
    def __init__(self, delay_seconds=None, notify=None, get_window=None, capture=None, live_capture=True):
        # Terminal version: live_capture=True, waits delay_seconds so you can switch windows.
        # Overlay version: live_capture=False, the screenshot arrives from the hotkey press.
        self.delay = config.SCREEN_DELAY_SECONDS if delay_seconds is None else delay_seconds
        self.notify = notify or (lambda message: None)
        self.get_window = get_window or get_active_window
        self.capture = capture or capture_active_window
        self.live_capture = live_capture

    def run(self, question, history, context=None):
        live = context is None
        if live:
            if not self.live_capture:
                return Reply(
                    "Screen access is off for this question. Tick 'Let AI Buddy look at this window', "
                    "or press the hotkey again from the window you want me to look at.",
                    remember=False,
                )
            if self.delay > 0:
                self.notify(f"Switch to the window you want me to look at. Capturing in {self.delay:g} seconds...")
                time.sleep(self.delay)
            context = take_snapshot(self.get_window, self.capture)

        if context.blocked:
            return Reply(
                f"I won't read this window ({context.info.app}) because it matches your privacy blocklist.",
                remember=False,
            )
        if context.capture is None:
            return Reply(f"I couldn't capture the screen: {context.error or 'unknown error'}", remember=False)

        info, shot = context.info, context.capture
        if live:
            if info:
                what = f"{info.app}: {info.title or 'untitled window'}"
                if shot.scope == "screen":
                    what += " (window area unavailable, used the full screen)"
            else:
                what = "full screen (window detection works on Windows only)"
            note = f"Captured {what}."
            if config.SAVE_LAST_CAPTURE:
                note += f" Preview saved to {config.LAST_CAPTURE_PATH}"
            self.notify(note)

        header = f"Active window: {info.app} - {info.title}\n" if info else ""
        text = llm.generate(
            f"{header}Question: {question}",
            system=SYSTEM_PROMPT,
            history=history,
            images=[(shot.jpeg, "image/jpeg")],
        )
        return Reply(text.strip() or "I didn't get a response from the model. Please try again.")
