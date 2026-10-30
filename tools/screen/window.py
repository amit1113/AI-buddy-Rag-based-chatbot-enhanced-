"""Which window is the user looking at? Windows only for now; other systems get None
and the screen tool falls back to capturing the whole screen."""
import os
import sys
from dataclasses import dataclass

_dpi_done = False

SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}  # desktop and taskbar
WS_EX_TOOLWINDOW = 0x80
GWL_EXSTYLE = -20
GW_HWNDNEXT = 2
DWMWA_CLOAKED = 14


@dataclass
class WindowInfo:
    title: str
    app: str    # process name, e.g. "chrome.exe"
    rect: tuple  # (left, top, right, bottom) in physical pixels, or None if minimised
    hwnd: int = 0  # Windows handle, so the same window can be found again later


def enable_dpi_awareness():
    """Without this, display scaling (125%, 150%...) makes window coordinates and
    screenshot pixels disagree, so the crop lands in the wrong place. Call it once at startup,
    before any window is created. Does nothing outside Windows."""
    global _dpi_done
    if _dpi_done or sys.platform != "win32":
        return
    _dpi_done = True
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _windows_api():
    import ctypes
    from ctypes import wintypes

    import psutil

    enable_dpi_awareness()
    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi

    # Declare types so 64-bit window handles are not truncated.
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsWindow.argtypes = [wintypes.HWND]
    dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    return ctypes, wintypes, psutil, user32, dwmapi


def _info_from_hwnd(api, hwnd):
    ctypes, wintypes, psutil, user32, dwmapi = api

    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    title = buffer.value

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        app = psutil.Process(pid.value).name()
    except Exception:
        app = "unknown"

    box = None
    if not user32.IsIconic(hwnd):  # minimised windows have no usable rectangle
        rect = wintypes.RECT()
        # Attribute 9 = visible frame without the invisible resize borders Windows 10/11 adds.
        if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
        box = (rect.left, rect.top, rect.right, rect.bottom)
    return WindowInfo(title=title, app=app, rect=box, hwnd=int(hwnd))


def _pid_of(api, hwnd):
    ctypes, wintypes, _psutil, user32, _dwm = api
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _is_candidate(api, hwnd, own_pid):
    """An ordinary window the user could be working in: visible, not minimised, not ours."""
    ctypes, wintypes, _psutil, user32, dwmapi = api
    if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return False
    if _pid_of(api, hwnd) == own_pid:
        return False
    cloaked = wintypes.DWORD(0)  # hidden "ghost" windows of modern apps report as visible but cloaked
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 and cloaked.value:
        return False
    if user32.GetWindowTextLengthW(hwnd) == 0:
        return False
    class_name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_name, 256)
    if class_name.value in SHELL_CLASSES:
        return False
    return not (user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW)


def _get_active_window_windows():
    """The window the user is working in. If the foreground window is AI Buddy's own (for example right
    after the overlay is hidden), fall back to the top-most ordinary window instead."""
    api = _windows_api()
    ctypes, wintypes, _psutil, user32, _dwm = api
    own_pid = os.getpid()
    hwnd = user32.GetForegroundWindow()
    if hwnd and _pid_of(api, hwnd) != own_pid:
        return _info_from_hwnd(api, hwnd)

    user32.GetTopWindow.restype = wintypes.HWND
    user32.GetTopWindow.argtypes = [wintypes.HWND]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    hwnd = user32.GetTopWindow(None)
    for _ in range(300):  # walk the windows from front to back
        if not hwnd:
            return None
        if _is_candidate(api, hwnd, own_pid):
            return _info_from_hwnd(api, hwnd)
        hwnd = user32.GetWindow(hwnd, GW_HWNDNEXT)
    return None


def focus_window(info):
    """Give keyboard focus back to a window (used when the overlay closes). Best effort."""
    if sys.platform != "win32" or info is None or not info.hwnd:
        return False
    try:
        api = _windows_api()
        wintypes, user32 = api[1], api[3]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        if not user32.IsWindow(info.hwnd):
            return False
        user32.SetForegroundWindow(info.hwnd)
        if user32.GetForegroundWindow() != info.hwnd:
            user32.keybd_event(0x12, 0, 0, 0)  # tap Alt: lets a background program take focus
            user32.keybd_event(0x12, 0, 2, 0)
            user32.SetForegroundWindow(info.hwnd)
        return True
    except Exception:
        return False


def refresh_window(info):
    """Current title and position of a window seen earlier. None if it has been closed.
    Where windows cannot be tracked (not Windows), the old info is returned unchanged."""
    if info is None or not info.hwnd or sys.platform != "win32":
        return info
    try:
        api = _windows_api()
        if not api[3].IsWindow(info.hwnd):
            return None
        return _info_from_hwnd(api, info.hwnd)
    except Exception:
        return info  # best effort: use what we knew


def get_active_window():
    """Return WindowInfo for the foreground window, or None if it can't be determined."""
    if sys.platform != "win32":
        return None
    try:
        return _get_active_window_windows()
    except Exception:
        return None
