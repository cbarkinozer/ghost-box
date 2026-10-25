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

    def remove_sources(self, identifiers):
        """Drop whole dependent sessions: derived answers can quote removed mail too."""
        current = self.sessions[self.session] if self.session >= 0 else None
        self.sessions = [session for session in self.sessions if not any(
            identifiers.intersection(message.get('sources', {})) for message in session['messages'])]
        retained = next((i for i, session in enumerate(self.sessions) if session is current), None)
        if retained is not None:
            self.session = retained
        elif self.sessions:
            self.session = len(self.sessions) - 1
            self.message = len(self.sessions[self.session]['messages']) - 1
        else:
            self.session = self.message = -1

    def clear(self):
        self.sessions.clear()
        self.session = self.message = -1
