"""Global hotkey. On Windows it uses the system's RegisterHotKey (the key combination is consumed,
so the app in front never sees it). Other systems fall back to pynput."""
import ctypes
import sys
import threading

MODIFIERS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
SPECIAL_KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B}
SPECIAL_KEYS.update({f"f{i}": 0x6F + i for i in range(1, 13)})  # F1 = 0x70
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEY_ID = 1


def parse_hotkey(text):
    """'ctrl+alt+space' -> (modifier flags, virtual-key code)."""
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    modifiers, key = 0, None
    for part in parts:
        if part in MODIFIERS:
            modifiers |= MODIFIERS[part]
        elif key is None:
            key = part
        else:
            raise ValueError(f"Hotkey '{text}' has more than one non-modifier key.")
    if key is None or modifiers == 0:
        raise ValueError("A hotkey needs at least one modifier and one key, e.g. ctrl+alt+space.")
    if key in SPECIAL_KEYS:
        return modifiers, SPECIAL_KEYS[key]
    if len(key) == 1 and key.isalnum():
        return modifiers, ord(key.upper())
    raise ValueError(f"Unknown key '{key}' in hotkey '{text}'.")


def to_pynput(text):
    """'ctrl+alt+space' -> '<ctrl>+<alt>+<space>' (pynput's notation)."""
    names = {"control": "ctrl", "win": "cmd", "escape": "esc"}
    out = []
    for part in (p.strip().lower() for p in text.split("+") if p.strip()):
        part = names.get(part, part)
        out.append(f"<{part}>" if len(part) > 1 else part)
    return "+".join(out)


class HotkeyListener:
    def __init__(self, hotkey, on_press):
        self.hotkey = hotkey
        self.on_press = on_press
        self._thread = None
        self._thread_id = None
        self._listener = None
        self._ready = threading.Event()
        self._error = None

    def start(self):
        """Start listening. Raises RuntimeError if the hotkey cannot be registered."""
        parse_hotkey(self.hotkey)  # validate early with a clear message
        if sys.platform == "win32":
            self._thread = threading.Thread(target=self._run_windows, daemon=True)
            self._thread.start()
            self._ready.wait(timeout=3)
            if self._error:
                raise RuntimeError(self._error)
        else:
            self._start_pynput()

    def stop(self):
        if sys.platform == "win32":
            if self._thread_id is not None:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        elif self._listener is not None:
            self._listener.stop()

    # ---- Windows ----
    def _run_windows(self):
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        modifiers, vk = parse_hotkey(self.hotkey)
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

        self._thread_id = kernel32.GetCurrentThreadId()
        # The hotkey must be registered by the same thread that reads its messages.
        if not user32.RegisterHotKey(None, HOTKEY_ID, modifiers | MOD_NOREPEAT, vk):
            self._error = (
                f"Could not register the hotkey {self.hotkey}. Another program may already use it. "
                "Set a different one with HOTKEY=ctrl+alt+b in your .env file."
            )
            self._ready.set()
            return
        self._ready.set()

        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == WM_HOTKEY:
                try:
                    self.on_press()
                except Exception as exc:  # a failing callback must not kill the listener
                    print(f"Hotkey handler error: {exc}")
        user32.UnregisterHotKey(None, HOTKEY_ID)

    # ---- other systems ----
    def _start_pynput(self):
        try:
            from pynput import keyboard
        except ImportError as exc:
            raise RuntimeError("Install pynput for hotkeys on this system: pip install pynput") from exc
        self._listener = keyboard.GlobalHotKeys({to_pynput(self.hotkey): self.on_press})
        self._listener.start()
