"""Tkinter overlay window. Deliberately thin: it shows things and forwards input to the presenter."""
import io
import queue
import sys
import traceback

import tkinter as tk

BG, BG_INPUT, FG, MUTED, ACCENT, ERROR = "#1e1f26", "#2b2d38", "#e8e9ed", "#9a9db0", "#7c8cff", "#ff8a8a"
BASE_WIDTH = 680
CHARS_PER_LINE = 85
MAX_TRANSCRIPT_LINES = 18
MIN_TRANSCRIPT_LINES = 3

# role -> (label shown before the text, tag for the label, tag for the text)
ROLES = {
    "you": ("You  ", "label_you", "you"),
    "buddy": ("Buddy  ", "label_buddy", "buddy"),
    "error": ("", "error", "error"),
    "system": ("", "system", "system"),
}


def estimate_lines(label, text, note):
    """Rough number of rows a message takes, used to size the conversation box."""
    rows = 0
    for index, line in enumerate(text.split("\n")):
        length = len(line) + (len(label) if index == 0 else 0)
        rows += max(1, -(-length // CHARS_PER_LINE))
    return rows + (1 if note else 0) + 1  # +1 for the blank line between messages


class TkOverlayView:
    def __init__(self):
        self.presenter = None
        self._queue = queue.Queue()
        self._visible = False
        self._thumbnail = None  # keep a reference or Tk drops the image
        self._lines = 0         # estimated rows currently in the conversation

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)
        self.root.report_callback_exception = self._on_callback_error
        self.width = int(BASE_WIDTH * (self.root.winfo_fpixels("1i") / 96.0))

        body = tk.Frame(self.root, bg=BG, padx=14, pady=12, highlightthickness=1, highlightbackground=ACCENT)
        body.pack(fill="both", expand=True)

        header = tk.Frame(body, bg=BG)
        header.pack(fill="x")
        self.thumbnail_label = tk.Label(header, bg=BG)
        self.thumbnail_label.pack(side="left", padx=(0, 10))
        details = tk.Frame(header, bg=BG)
        details.pack(side="left", fill="x", expand=True)
        self.context_label = tk.Label(
            details, text="", bg=BG, fg=MUTED, anchor="w", justify="left",
            font=("Segoe UI", 9), wraplength=self.width - 260,
        )
        self.context_label.pack(fill="x")
        self.include_var = tk.BooleanVar(value=True)
        self.include_check = tk.Checkbutton(
            details, text="Let AI Buddy look at this window if my question needs it", variable=self.include_var,
            bg=BG, fg=FG, selectcolor=BG_INPUT, activebackground=BG, activeforeground=FG,
            anchor="w", font=("Segoe UI", 9),
        )
        self.include_check.pack(fill="x")

        self.entry = tk.Entry(
            body, bg=BG_INPUT, fg=FG, insertbackground=FG, relief="flat", font=("Segoe UI", 13),
        )
        self.entry.pack(fill="x", pady=(10, 0), ipady=8)
        self.entry.bind("<Return>", self._on_return)

        self.status_label = tk.Label(body, text="", bg=BG, fg=MUTED, anchor="w", font=("Segoe UI", 9))
        self.status_label.pack(fill="x", pady=(6, 0))

        # The conversation. Read-only, scrolls with the mouse wheel, selectable for copying.
        self.transcript = tk.Text(
            body, wrap="word", height=MIN_TRANSCRIPT_LINES, bg=BG, fg=FG, relief="flat",
            font=("Segoe UI", 11), padx=2, pady=4, state="disabled", cursor="arrow", highlightthickness=0,
        )  # packed only once there is something to show
        self.transcript.tag_configure("label_you", foreground=ACCENT, font=("Segoe UI", 11, "bold"))
        self.transcript.tag_configure("label_buddy", foreground=MUTED, font=("Segoe UI", 11, "bold"))
        self.transcript.tag_configure("you", foreground=FG)
        self.transcript.tag_configure("buddy", foreground=FG)
        self.transcript.tag_configure("note", foreground=MUTED, font=("Segoe UI", 9))
        self.transcript.tag_configure("error", foreground=ERROR)
        self.transcript.tag_configure("system", foreground=MUTED, font=("Segoe UI", 10, "italic"))

        self.root.bind_all("<Escape>", lambda event: self._on_escape())

    # ---- wiring ----
    def bind(self, presenter):
        self.presenter = presenter

    def run(self):
        self.root.after(50, self._poll)
        self.root.mainloop()

    def post(self, function):
        """Run function on the UI thread. Safe to call from any thread."""
        self._queue.put(function)

    def _poll(self):
        try:
            while True:
                try:
                    function = self._queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    function()
                except Exception:
                    traceback.print_exc()
        finally:
            self.root.after(50, self._poll)

    def _on_return(self, event):
        text = self.entry.get()
        if text.strip() and self.presenter:
            self.entry.delete(0, "end")
            self.presenter.submit(text, self.include_var.get())
        return "break"

    def _on_escape(self):
        if self.presenter:
            self.presenter.hide()  # also returns focus to the window you came from
        else:
            self.hide()

    def _on_callback_error(self, exc_type, value, trace):
        if issubclass(exc_type, KeyboardInterrupt):  # Ctrl+C in the console
            self.quit()
        else:
            traceback.print_exception(exc_type, value, trace)

    # ---- the view interface used by the presenter ----
    def is_visible(self):
        return self._visible

    def set_context(self, label, thumbnail_jpeg, can_include):
        self.context_label.config(text=label)
        self.include_var.set(can_include)
        self.include_check.config(state="normal" if can_include else "disabled")
        self._thumbnail = None
        if thumbnail_jpeg:
            try:
                from PIL import Image, ImageTk

                image = Image.open(io.BytesIO(thumbnail_jpeg))
                image.thumbnail((180, 110))
                self._thumbnail = ImageTk.PhotoImage(image)
            except Exception:
                self._thumbnail = None
        self.thumbnail_label.config(image=self._thumbnail or "")

    def set_busy(self, busy, question):
        self.status_label.config(text=f"Thinking about: {question[:70]}" if busy else "")

    def append_message(self, role, text, note=""):
        """Add one message to the bottom of the conversation and scroll to it."""
        label, label_tag, text_tag = ROLES[role]
        self.transcript.config(state="normal")
        if label:
            self.transcript.insert("end", label, label_tag)
        self.transcript.insert("end", text, text_tag)
        if note:
            self.transcript.insert("end", "\n" + note, "note")
        self.transcript.insert("end", "\n\n")
        self.transcript.config(state="disabled")
        self._lines += estimate_lines(label, text, note)
        self._fit_transcript()
        self.transcript.see("end")
        if role != "you":
            self.entry.focus_set()

    def clear_transcript(self):
        self.transcript.config(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.config(state="disabled")
        self._lines = 0
        self.transcript.pack_forget()
        self._resize()

    def show(self):
        self._resize()
        self.root.deiconify()
        self.root.lift()
        self._visible = True
        self._force_foreground()
        self.entry.focus_force()
        self.transcript.see("end")

    def hide(self):
        self.root.withdraw()
        self._visible = False

    def quit(self):
        self.root.destroy()

    # ---- helpers ----
    def _fit_transcript(self):
        """Grow the conversation box with its content, up to a maximum; beyond that it scrolls."""
        height = min(MAX_TRANSCRIPT_LINES, max(MIN_TRANSCRIPT_LINES, self._lines))
        self.transcript.config(height=height)
        self.transcript.pack(fill="x", pady=(6, 0))
        self._resize()

    def _resize(self):
        self.root.update_idletasks()
        height = self.root.winfo_reqheight()
        x = (self.root.winfo_screenwidth() - self.width) // 2
        y = int(self.root.winfo_screenheight() * 0.15)
        self.root.geometry(f"{self.width}x{height}+{x}+{y}")

    def _force_foreground(self):
        """Windows refuses to let a background program take focus. Try politely first;
        if that fails, tap the Alt key, a well-known way to lift the restriction."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32
            user32.GetParent.restype = ctypes.c_void_p
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
            window_id = self.root.winfo_id()
            hwnd = user32.GetParent(window_id) or window_id
            user32.SetForegroundWindow(hwnd)
            if user32.GetForegroundWindow() != hwnd:
                user32.keybd_event(0x12, 0, 0, 0)  # Alt down
                user32.keybd_event(0x12, 0, 2, 0)  # Alt up
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass  # worst case the user clicks the window once
