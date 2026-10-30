"""A snapshot of what the user is looking at: window details plus a screenshot."""
from dataclasses import dataclass

from core import config
from .capture import Capture, capture_active_window
from .window import WindowInfo, get_active_window, refresh_window


@dataclass
class ScreenContext:
    info: WindowInfo = None
    capture: Capture = None
    blocked: bool = False   # window matched the privacy blocklist, so nothing was captured
    error: str = None       # capture failed for this reason

    @property
    def usable(self):
        return self.capture is not None and not self.blocked


def is_blocked(info, blocklist):
    """True if the window's app name or title contains a blocklisted word."""
    haystack = f"{info.app} {info.title}".lower()
    return any(word and word in haystack for word in blocklist)


def take_snapshot(get_window=get_active_window, capture=capture_active_window):
    """Identify the active window and capture it. Blocklisted windows are never captured."""
    info = None
    try:
        info = get_window()
        if info and is_blocked(info, config.SCREEN_BLOCKLIST):
            return ScreenContext(info=info, blocked=True)
        return ScreenContext(info=info, capture=capture(info))
    except Exception as exc:
        return ScreenContext(info=info, error=str(exc)[:200])


def snapshot_window(info, refresh=refresh_window, capture=capture_active_window):
    """Capture a window noted earlier (for example when the hotkey was pressed). Its position and title
    are re-read first, and the privacy blocklist is checked again, because it may have changed."""
    try:
        if info is not None:
            fresh = refresh(info)
            if fresh is None:
                return ScreenContext(info=info, error="that window is no longer open")
            info = fresh
            if is_blocked(info, config.SCREEN_BLOCKLIST):
                return ScreenContext(info=info, blocked=True)
        return ScreenContext(info=info, capture=capture(info))
    except Exception as exc:
        return ScreenContext(info=info, error=str(exc)[:200])


class ScreenSource:
    """A window the assistant MAY look at. Nothing is captured until capture() is called, which
    only happens when the question needs the screen."""

    def __init__(self, info=None, blocked=False, capture_fn=None):
        self.info = info
        self.blocked = blocked
        self._capture_fn = capture_fn

    @property
    def available(self):
        return not self.blocked and self._capture_fn is not None

    @property
    def app(self):
        return self.info.app if self.info else ""

    def capture(self):
        if self.blocked:
            return ScreenContext(info=self.info, blocked=True)
        return self._capture_fn()
