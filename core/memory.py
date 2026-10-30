"""Short-term conversation memory shared by every tool."""


class ConversationMemory:
    def __init__(self, max_messages=20):
        self.max_messages = max_messages
        self._messages = []  # [(role, text)], role is "user" or "assistant"

    def add(self, role, text):
        self._messages.append((role, text))
        if len(self._messages) > self.max_messages:
            self._messages = self._messages[-self.max_messages:]
            while self._messages and self._messages[0][0] != "user":  # always start on a user turn
                self._messages.pop(0)

    def messages(self):
        return list(self._messages)

    def clear(self):
        self._messages = []
