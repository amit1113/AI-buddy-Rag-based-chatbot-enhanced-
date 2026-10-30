"""AI Buddy overlay: press the hotkey from any window, ask a question.  Run:  python buddy.py"""
from core import config
from core.assistant import Assistant
from tools.chat import ChatTool
from tools.docs import DocsTool
from tools.screen import ScreenTool
from tools.screen.window import enable_dpi_awareness


def main():
    enable_dpi_awareness()  # must happen before the window exists, or text looks blurry on scaled displays

    try:
        from app.overlay import TkOverlayView
    except ImportError as exc:
        print(f"Could not load the window toolkit ({exc}). Reinstall Python with the 'tcl/tk' option ticked.")
        return
    from app.hotkey import HotkeyListener
    from app.presenter import OverlayPresenter

    assistant = Assistant(tools={
        "chat": ChatTool(),
        "doc": DocsTool(),
        "screen": ScreenTool(live_capture=False),  # the overlay supplies the screenshot, only when needed
    })
    view = TkOverlayView()
    presenter = OverlayPresenter(assistant, view)
    view.bind(presenter)

    listener = HotkeyListener(config.HOTKEY, presenter.on_hotkey)
    try:
        listener.start()
    except (RuntimeError, ValueError) as exc:
        print(exc)
        return

    print(f"AI Buddy is running. Press {config.HOTKEY} from any window.")
    print("Esc hides the box. Type /quit in the box to stop AI Buddy (or close this window).")
    try:
        view.run()
    finally:
        listener.stop()


if __name__ == "__main__":
    main()
