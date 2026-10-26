"""Background account operations with sanitized errors."""

from PySide6.QtCore import QThread, Signal
from ..mail.errors import AccountError


class AccountTask(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.succeeded.emit(self.operation())
        except AccountError as error:
            self.failed.emit(str(error))
        except FileNotFoundError:
            self.failed.emit(
                "Google sign-in is not configured in this build. "
                "Please ask the Ghost-box maintainer for a configured build."
            )
        except Exception:
            # OAuth exceptions can contain authorization URLs or token responses.
            self.failed.emit(
                "Account operation failed. Check your internet connection and "
                "OS credential-store permissions. Your organization may also restrict access. "
                "If sign-in was cancelled or timed out, try again."
            )

