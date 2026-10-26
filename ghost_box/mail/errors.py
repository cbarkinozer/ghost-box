"""Safe account errors shared by the mail providers."""


class AccountError(RuntimeError):
    """Application-authored diagnostic; never an OAuth/API response body."""


class SendError(AccountError):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain
