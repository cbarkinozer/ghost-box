"""Session-only email storage. No files, database, or disk cache."""


class MailStore:
    def __init__(self):
        self.accounts = {}

    def replace(self, account, messages):
        # Called only after a complete fetch; cancellation leaves this untouched.
        self.accounts[account] = {message["id"]: message for message in messages}

    def clear(self):
        self.accounts.clear()


def messages(store, account):
    return sorted(store.accounts.get(account, {}).values(),
                  key=lambda message: (-message["timestamp"], message["id"]))


def message(store, account, identifier):
    return store.accounts.get(account, {}).get(identifier)
