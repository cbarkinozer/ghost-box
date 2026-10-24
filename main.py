"""Ghost-box desktop window. Run with: uv run --locked main.py."""

import os
from pathlib import Path
import stat
import sys
from datetime import datetime

from PySide6.QtCore import QDate, QDateTime, QLibraryInfo, QStandardPaths, QTime, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QMessageBox, QPushButton,
    QToolBar, QDateTimeEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QSplitter,
)

import gmail
import mail_store


def prepare_qt_plugins():
    """Qt skips macOS-hidden plugin files, even when their path is correct."""
    if sys.platform != "darwin":
        return
    root = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    for path in (root, *root.rglob("*")):
        flags = path.stat().st_flags
        if flags & stat.UF_HIDDEN:
            os.chflags(path, flags & ~stat.UF_HIDDEN)


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
        except gmail.AccountError as error:
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


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ghost-box")
        self.resize(960, 640)
        self.task = None
        self.email = ""
        self.database = Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )) / "mail.sqlite3"

        toolbar = QToolBar("Account")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.connect_button = QPushButton("Connect Gmail")
        self.connect_button.clicked.connect(self.connect_gmail)
        toolbar.addWidget(self.connect_button)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(lambda: self.start(gmail.disconnect))
        toolbar.addWidget(self.disconnect_button)

        dates = QToolBar("Fetch")
        dates.setMovable(False)
        self.addToolBarBreak()
        self.addToolBar(dates)
        self.first = QDateTimeEdit(QDateTime(QDate.currentDate(), QTime(0, 0)))
        self.last = QDateTimeEdit(QDateTime(QDate.currentDate(), QTime(23, 59)))
        for label, control in (("From ", self.first), (" To ", self.last)):
            dates.addWidget(QLabel(label))
            control.setCalendarPopup(True)
            control.setDisplayFormat("yyyy-MM-dd HH:mm")
            control.setToolTip("Local time. The full To minute is included.")
            dates.addWidget(control)
        self.fetch_button = QPushButton("Fetch")
        self.fetch_button.clicked.connect(self.fetch_mail)
        dates.addWidget(self.fetch_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(lambda: self.task.requestInterruption())
        dates.addWidget(self.cancel_button)

        self.mail_list = QListWidget()
        self.mail_list.currentItemChanged.connect(self.read_message)
        self.reader = QPlainTextEdit()
        self.reader.setReadOnly(True)
        self.reader.setPlaceholderText("Fetch today's mail, then select a message.\nTimes are local. Each successful fetch replaces this account's previous local emails.\nSent mail is included; Spam, Trash, and Drafts are excluded.")
        splitter = QSplitter()
        splitter.addWidget(self.mail_list)
        splitter.addWidget(self.reader)
        splitter.setSizes([320, 640])
        self.setCentralWidget(splitter)
        self.start(gmail.saved_account)

    def start(self, operation, success=None):
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self.fetch_button.setEnabled(False)
        self.first.setEnabled(False)
        self.last.setEnabled(False)
        self.statusBar().showMessage("Checking account…")
        self.task = AccountTask(operation, self)
        self.task.succeeded.connect(success or self.show_account)
        self.task.failed.connect(self.show_error)
        self.task.progress.connect(self.statusBar().showMessage)
        self.task.finished.connect(self.task_finished)
        self.task.start()

    def connect_gmail(self):
        self.start(gmail.connect)
        self.statusBar().showMessage("Complete Google sign-in in your browser (60-second timeout)…")

    def show_account(self, email):
        self.email = email
        self.statusBar().showMessage(
            f"Saved account: {email} · Read-only"
            if email else "Gmail is not connected."
        )
        self.refresh_messages()

    def refresh_messages(self):
        self.mail_list.clear()
        self.reader.clear()
        if self.email:
            for message in mail_store.messages(self.database, self.email):
                date = datetime.fromtimestamp(message["timestamp"] / 1000).strftime("%Y-%m-%d %H:%M")
                item = QListWidgetItem(f"{date} · {message['sender']}\n{message['subject']}")
                item.setData(Qt.ItemDataRole.UserRole, message["id"])
                self.mail_list.addItem(item)

    def read_message(self, item):
        if not item:
            self.reader.clear()
            return
        message = mail_store.message(self.database, self.email, item.data(Qt.ItemDataRole.UserRole))
        if message:
            self.reader.setPlainText(
                f"From: {message['sender']}\nTo: {message['recipients']}\n"
                f"Subject: {message['subject']}\n\n{message['body']}"
            )

    def fetch_mail(self):
        first = self.first.dateTime().toPython()
        last = self.last.dateTime().toPython()
        if first > last:
            QMessageBox.warning(self, "Date range", "From must be on or before To.")
            return
        account = self.email
        self.start(lambda: gmail.fetch(
            first, last, self.database, account,
            self.task.progress.emit, self.task.isInterruptionRequested,
        ), self.fetched)
        self.cancel_button.setEnabled(True)
        self.statusBar().showMessage("Fetching selected local times; previous emails will be replaced on success…")

    def fetched(self, result):
        self.refresh_messages()
        state = "Fetch cancelled; previous emails kept" if result["cancelled"] else "Fetch complete; previous local emails replaced"
        self.statusBar().showMessage(
            f"{state}. {result['count']} messages processed."
        )

    def show_error(self, message):
        self.refresh_messages()
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, "Gmail", message)

    def task_finished(self):
        self.connect_button.setEnabled(not bool(self.email))
        self.disconnect_button.setEnabled(bool(self.email))
        self.fetch_button.setEnabled(bool(self.email))
        self.cancel_button.setEnabled(False)
        self.first.setEnabled(True)
        self.last.setEnabled(True)
        self.task.deleteLater()
        self.task = None

    def closeEvent(self, event):
        if self.task is not None:
            self.task.requestInterruption()
            self.statusBar().showMessage("Stopping; waiting for the current request or sign-in timeout before closing. Close again when finished.")
            event.ignore()
        else:
            event.accept()


def main() -> int:
    prepare_qt_plugins()
    app = QApplication(sys.argv)
    app.setApplicationName("Ghost-box")

    window = Window()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
