"""Terminal version of AI Buddy (steps 2-5).  Run:  python cli.py"""
from core.assistant import Assistant
from tools.chat import ChatTool
from tools.docs import DocsTool
from tools.screen import ScreenTool


def say(message):
    print(f"\nbuddy> {message}", flush=True)


def build_assistant():
    return Assistant(
        tools={"chat": ChatTool(), "doc": DocsTool(), "screen": ScreenTool(notify=say)}
    )


def print_reply(reply):
    print(f"\nbuddy> {reply.text}")
    if reply.routed_by:
        print(f"       routed to {reply.tool} ({reply.routed_by})")
    if reply.sources:
        cited = "; ".join(f"{s['file']} p.{s['page']}" for s in reply.sources)
        print(f"       sources: {cited}")


def main():
    assistant = build_assistant()
    print("AI Buddy ready. Type /help for commands, or just start chatting.")
    while True:
        try:
            message = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not message:
            continue
        try:
            reply = assistant.handle(message)
        except KeyboardInterrupt:
            print("\n(cancelled)")
            continue
        except Exception as exc:  # keep the session alive after API errors
            print(f"\nbuddy> Something went wrong: {str(exc)[:300]}")
            continue
        print_reply(reply)
        if reply.end:
            break


if __name__ == "__main__":
    main()
