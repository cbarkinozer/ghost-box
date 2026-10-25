"""Tiny session/message container. Never serialized or written to preferences."""


class History:
    def __init__(self):
        self.sessions = []
        self.session = -1
        self.message = -1

    @property
    def current(self):
        if self.session < 0 or self.message < 0:
            return None
        return self.sessions[self.session]['messages'][self.message]

    def append(self, record, new_session=False):
        if new_session or self.session < 0:
            self.sessions.append({'title': record['question'][:65], 'messages': []})
            self.session = len(self.sessions) - 1
        messages = self.sessions[self.session]['messages']
        messages.append(record)
        self.message = len(messages) - 1

    def select(self, session, message=None):
        self.session = session
        self.message = len(self.sessions[session]['messages']) - 1 if message is None else message
        return self.current

    def clear(self):
        self.sessions.clear()
        self.session = self.message = -1
