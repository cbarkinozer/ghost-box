"""Session-only email storage. No files, database, or disk cache."""


class MailStore:
    def __init__(self):
        self.accounts = {}
        self.coverage = {}

    def replace(self, account, messages, coverage=None):
        # Called only after a complete fetch; cancellation leaves this untouched.
        self.accounts[account] = {message["id"]: message for message in messages}
        self.coverage.pop(account, None)
        if coverage is not None:
            self.coverage[account] = coverage.copy()

    def remove(self, account, identifiers):
        messages = self.accounts.get(account, {})
        for identifier in identifiers:
            messages.pop(identifier, None)

    def clear(self):
        self.accounts.clear()
        self.coverage.clear()


def messages(store, account):
    return sorted(store.accounts.get(account, {}).values(),
                  key=lambda message: (-message["timestamp"], message["id"]))


def message(store, account, identifier):
    return store.accounts.get(account, {}).get(identifier)
