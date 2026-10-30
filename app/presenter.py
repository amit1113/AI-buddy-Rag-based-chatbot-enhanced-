"""All overlay behaviour, with no widgets in it, so it can be tested without a screen.
The view (app/overlay.py) only shows things and forwards clicks and key presses.

Screen privacy flow: pressing the hotkey only NOTES which window you were in (its name and position,
no pixels). A screenshot is taken only if your question turns out to need the screen: the box hides
for a moment, the window is captured, and the box comes back."""
import threading
import time
from dataclasses import dataclass

from core import config
from tools.screen.context import ScreenSource, is_blocked, snapshot_window
from tools.screen.window import focus_window, get_active_window


@dataclass
class Target:
    """The window the user was in when they pressed the hotkey."""
    info: object = None
    blocked: bool = False


def find_target(get_window=get_active_window):
    """Note the active window. Metadata only; nothing is captured here."""
    try:
        info = get_window()
    except Exception:
        info = None
    blocked = bool(info and is_blocked(info, config.SCREEN_BLOCKLIST))
    return Target(info=info, blocked=blocked)


def describe_target(target):
    """(label, can_allow_screen) for the line above the input box."""
    if target is None:
        return "No window detected.", False
    if target.blocked:
        return f"Screen access off: {target.info.app} is on your privacy blocklist.", False
    if target.info is None:
        return "Your screen can be looked at if your question needs it.", True
    label = f"Window: {target.info.app} \u2014 {target.info.title}" if target.info.title else f"Window: {target.info.app}"
    return label[:90], True


def plain_text(markdown):
    """Light clean-up so the model's markdown reads well in a plain text box."""
    lines = []
    for line in markdown.replace("**", "").replace("`", "").split("\n"):
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if stripped.startswith(("* ", "- ")):
            line = f"{indent}\u2022 {stripped[2:]}"
        elif stripped.startswith("#"):
            line = stripped.lstrip("#").strip()
        lines.append(line)
    return "\n".join(lines).strip()


def sources_line(reply):
    if not reply.sources:
        return ""
    return "Sources: " + "; ".join(f"{s['file']} p.{s['page']}" for s in reply.sources)


def reply_note(reply):
    """Small grey line under an answer: which tool was picked, and the sources."""
    parts = []
    if reply.routed_by:
        parts.append(f"routed to {reply.tool} ({reply.routed_by})")
    elif reply.tool == "screen":
        parts.append("looked at your screen")
    if reply.sources:
        parts.append(sources_line(reply))
    return " \u00b7 ".join(parts)


def _start_thread(function):
    threading.Thread(target=function, daemon=True).start()


class OverlayPresenter:
    def __init__(self, assistant, view, get_target=find_target, snapshot=snapshot_window,
                 run_in_thread=_start_thread, settle_seconds=None, sleep=time.sleep, focus=focus_window):
        self.assistant = assistant
        self.view = view
        self._get_target = get_target
        self._snapshot = snapshot
        self._run = run_in_thread
        self._settle = config.SCREEN_SETTLE_SECONDS if settle_seconds is None else settle_seconds
        self._sleep = sleep
        self._focus = focus
        self.target = None
        self.busy = False

    # ---- called from the hotkey thread ----
    def on_hotkey(self):
        if self.view.is_visible():
            self.view.post(self.hide)
            return
        target = self._get_target()  # which window are we in? (before the overlay takes focus)
        self.view.post(lambda: self._show(target))

    # ---- called on the UI thread ----
    def _show(self, target):
        self.target = target
        label, can_allow = describe_target(target)
        self.view.set_context(label, None, can_allow)
        self.view.show()  # the conversation so far stays visible

    def hide(self):
        """Close the box and hand keyboard focus back to the window the user was in."""
        self.view.hide()
        if self.target is not None and self.target.info is not None:
            self._focus(self.target.info)

    def submit(self, text, allow_screen):
        text = text.strip()
        if not text or self.busy:
            return
        source = None
        if allow_screen and self.target is not None and not self.target.blocked:
            source = ScreenSource(info=self.target.info, capture_fn=self._capture_target)
        self.busy = True
        self.view.append_message("you", text)
        self.view.set_busy(True, text)

        def work():
            try:
                reply = self.assistant.handle(text, screen_source=source)
            except Exception as exc:
                message = str(exc)[:300]  # copy now: 'exc' is deleted when this block ends
                self.view.post(lambda: self._failed(message))
                return
            self.view.post(lambda: self._done(reply))

        self._run(work)

    # ---- screen capture, called from the worker thread only when the question needs the screen ----
    def _capture_target(self):
        target = self.target
        hidden = threading.Event()

        def hide_now():
            self.view.hide()
            hidden.set()

        self.view.post(hide_now)
        hidden.wait(timeout=2)
        self._sleep(self._settle)  # let the window behind the box repaint
        try:
            context = self._snapshot(target.info if target else None)
        finally:
            self.view.post(self.view.show)  # always bring the box back
        if context.usable:
            thumbnail = context.capture.jpeg
            label, _ = describe_target(Target(info=context.info))
            self.view.post(lambda: self.view.set_context(label, thumbnail, True))
        return context

    def _done(self, reply):
        self.busy = False
        self.view.set_busy(False, "")
        if reply.clear:
            self.view.clear_transcript()
            self.view.append_message("system", reply.text)
        else:
            self.view.append_message("buddy", plain_text(reply.text), reply_note(reply))
        if reply.end:
            self.view.quit()

    def _failed(self, message):
        self.busy = False
        self.view.set_busy(False, "")
        self.view.append_message("error", f"Something went wrong: {message}")
