"""Ghost-box desktop window. Run with: uv run --locked main.py."""

import os
import json
import math
import platform
from importlib.util import find_spec
from pathlib import Path
import stat
import sys
from datetime import datetime

from PySide6.QtCore import QDate, QDateTime, QLibraryInfo, QProcess, QStandardPaths, QTime, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QMessageBox, QPushButton,
    QToolBar, QDateTimeEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QSplitter,
    QAbstractItemView, QHBoxLayout, QVBoxLayout, QWidget,
    QProgressBar,
)

import gmail
import mail_store
from caspy import ModelPanel
from mail_context import SYSTEM, SUMMARY, build_context


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
        self.resize(1180, 760)
        self.setMinimumSize(1000, 640)
        self.task = None
        self.inference = None
        self.summary_mode = False
        self.last_memory = ''
        self.inference_buffer = b""
        self.email = ""
        self.mailbox = mail_store.MailStore()
        # Remove mail files created by earlier versions before showing any mail.
        old_database = Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )) / "mail.sqlite3"
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(old_database) + suffix).unlink(missing_ok=True)

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
        self.mail_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.mail_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.mail_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.mail_list.currentItemChanged.connect(self.read_message)
        self.mail_list.itemSelectionChanged.connect(self.scope_changed)
        mail_panel = QWidget()
        mail_panel.setMinimumWidth(240)
        mail_layout = QVBoxLayout(mail_panel)
        mail_layout.addWidget(QLabel("<b>Emails</b>"))
        selection_buttons = QHBoxLayout()
        select_all = QPushButton("Select all")
        select_all.clicked.connect(self.mail_list.selectAll)
        selection_buttons.addWidget(select_all)
        clear_selection = QPushButton("Clear selection")
        clear_selection.clicked.connect(self.mail_list.clearSelection)
        selection_buttons.addWidget(clear_selection)
        mail_layout.addLayout(selection_buttons)
        mail_layout.addWidget(self.mail_list)
        self.reader = QPlainTextEdit()
        self.reader.setReadOnly(True)
        self.reader.setPlaceholderText("Fetch today's mail, then select a message.\nTimes are local. Each successful fetch replaces this account's previous session emails.\nMail is held in memory only and disappears when you close the app.\nSent mail is included; Spam, Trash, and Drafts are excluded.")
        reading_panel = QWidget()
        reading_panel.setMinimumWidth(420)
        reading_layout = QVBoxLayout(reading_panel)
        reading_layout.setContentsMargins(0, 0, 0, 0)
        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        preview_layout.addWidget(QLabel("<b>Email preview</b>"))
        preview_layout.addWidget(self.reader)
        preview.setMinimumHeight(140)
        conversation = QWidget()
        conversation.setMinimumHeight(230)
        conversation_layout = QVBoxLayout(conversation)
        conversation_layout.addWidget(QLabel("<b>Ask 👻 Caspy</b>"))
        self.scope_label = QLabel()
        self.scope_label.setWordWrap(True)
        self.scope_label.setToolTip("Includes selected email headers, question, and instructions. Approximately 4 characters per token; actual token counts vary.")
        conversation_layout.addWidget(self.scope_label)
        self.question = QPlainTextEdit()
        self.question.setPlaceholderText("Question for Ask, or optional instructions for Summarize…")
        self.question.setMaximumHeight(80)
        self.question.textChanged.connect(self.scope_changed)
        conversation_layout.addWidget(self.question)
        actions = QHBoxLayout()
        self.ask_button = QPushButton("Ask selected emails")
        self.ask_button.clicked.connect(self.ask_selected)
        actions.addWidget(self.ask_button)
        self.summary_button = QPushButton('Summarize')
        self.summary_button.setToolTip('Summarize selected emails. Text above is used as additional instructions; it stays in RAM.')
        self.summary_button.clicked.connect(lambda: self.ask_selected(summarize=True))
        actions.addWidget(self.summary_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_inference)
        actions.addWidget(self.stop_button)
        conversation_layout.addLayout(actions)
        self.inference_status = QLabel("Select emails and enter a question to begin.")
        self.inference_status.setWordWrap(True)
        self.inference_status.setTextFormat(Qt.TextFormat.PlainText)
        conversation_layout.addWidget(self.inference_status)
        self.task_progress = QProgressBar()
        self.task_progress.setFormat('%v / %m tasks complete')
        self.task_progress.hide()
        conversation_layout.addWidget(self.task_progress)
        self.answer = QPlainTextEdit()
        self.answer.setReadOnly(True)
        self.answer.setPlaceholderText("Answers stay in RAM. Select multiple emails with Cmd/Ctrl-click or Shift-click.")
        conversation_layout.addWidget(self.answer, 1)
        reading_split = QSplitter(Qt.Orientation.Vertical)
        reading_split.setChildrenCollapsible(False)
        reading_split.addWidget(preview)
        reading_split.addWidget(conversation)
        reading_split.setSizes([360, 300])
        reading_layout.addWidget(reading_split)
        content = QSplitter()
        content.setChildrenCollapsible(False)
        content.addWidget(mail_panel)
        content.addWidget(reading_panel)
        self.caspy = ModelPanel()
        self.caspy.setMinimumWidth(220)
        self.caspy.setMaximumWidth(260)
        self.caspy.selector.currentIndexChanged.connect(self.scope_changed)
        self.caspy.parameters_changed.connect(self.scope_changed)
        content.addWidget(self.caspy)
        content.setSizes([280, 660, 240])
        content.setStretchFactor(0, 0)
        content.setStretchFactor(1, 1)
        content.setStretchFactor(2, 0)
        self.setCentralWidget(content)
        self.scope_changed()
        self.start(gmail.saved_account)

    def start(self, operation, success=None):
        self.invalidate_answer()
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
        self.update_scope()

    def selected_messages(self):
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.mail_list.selectedItems()}
        return [message for message in mail_store.messages(self.mailbox, self.email)
                if message["id"] in selected]

    def update_scope(self):
        messages = self.selected_messages()
        characters = len(SYSTEM) + len(build_context(messages, self.question_text())) if messages else 0
        self.scope_label.setText(
            f"{len(messages)} emails selected · {characters:,} input characters · ~{math.ceil(characters / 4):,} tokens"
        )
        self.ask_button.setEnabled(bool(messages and self.question.toPlainText().strip())
                                   and self.task is None and self.inference is None)
        self.summary_button.setEnabled(bool(messages) and self.task is None and self.inference is None)

    def question_text(self):
        text = self.question.toPlainText().strip()
        return SUMMARY + ('\nAdditional instructions: ' + text if text else '') if self.summary_mode else text

    def scope_changed(self):
        self.summary_mode = False
        self.invalidate_answer()
        self.update_scope()
        if self.inference is None:
            self.inference_status.setText(
                "Ready to ask or summarize selected emails." if self.ask_button.isEnabled()
                else "Enter a question, or press Summarize." if self.summary_button.isEnabled()
                else "Select emails to begin."
            )

    def set_inference_status(self, text):
        self.inference_status.setText(text)
        self.statusBar().showMessage(text)

    def invalidate_answer(self):
        if self.inference is not None:
            self.stop_inference()
        self.answer.clear()
        self.task_progress.hide()

    def ask_selected(self, summarize=False):
        if self.inference is not None or self.task is not None:
            return
        self.summary_mode = summarize
        if not self.selected_messages() or (not summarize and not self.question.toPlainText().strip()):
            self.set_inference_status("Select at least one email and enter a question first.")
            return
        folder = self.caspy.selected_folder()
        if folder is None:
            self.set_inference_status("Select a downloaded preset or a local model folder first.")
            return
        is_gguf = folder.suffix.lower() == '.gguf'
        if not is_gguf and (sys.platform != "darwin" or platform.machine() != "arm64"):
            self.set_inference_status("This initial inference backend requires Apple Silicon macOS.")
            return
        if find_spec('llama_cpp' if is_gguf else 'mlx_lm') is None:
            extra = 'gguf' if is_gguf else 'inference'
            self.set_inference_status(f"Local runtime is missing. Restart with: uv run --locked --extra {extra} main.py")
            return
        try:
            parameters = self.caspy.parameters()
        except ValueError as error:
            self.set_inference_status(str(error))
            return
        process = QProcess(self)
        self.inference = process
        self.inference_buffer = b""
        self.answer.clear()
        self.inference_failed = False
        self.inference_stopped = False
        process.setProgram(sys.executable)
        process.setArguments(["-u", str(Path(__file__).with_name("inference_worker.py"))])
        process.readyReadStandardOutput.connect(self.read_inference)
        # Do not display or log raw runtime diagnostics; they may include inputs.
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.finished.connect(self.inference_finished)
        process.errorOccurred.connect(self.inference_error)
        request = {'folder': str(folder), 'emails': self.selected_messages(),
                   'question': self.question_text(), 'parameters': parameters}
        def send_request():
            process.write(json.dumps(request).encode() + b"\n")
            process.closeWriteChannel()
        process.started.connect(send_request)
        self.stop_button.setEnabled(True)
        self.task_progress.setRange(0, 0)
        self.task_progress.show()
        self.last_memory = ''
        self.caspy.memory.setText('Loading model; measuring memory…')
        self.set_inference_status("Starting local inference… The model loads for each question.")
        self.update_scope()
        process.start()

    def read_inference(self):
        if self.inference is None:
            return
        self.inference_buffer += bytes(self.inference.readAllStandardOutput())
        while b"\n" in self.inference_buffer:
            line, self.inference_buffer = self.inference_buffer.split(b"\n", 1)
            if self.inference_stopped:
                continue
            try:
                event = json.loads(line)
                kind, text = event["kind"], event["text"]
            except (ValueError, KeyError, TypeError):
                continue
            if kind == "text":
                cursor = self.answer.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                cursor.insertText(text)
                self.answer.setTextCursor(cursor)
            elif kind in ("status", "error"):
                self.inference_failed |= kind == "error"
                self.set_inference_status(text)
            elif kind == 'progress':
                self.task_progress.setRange(0, event['total'])
                self.task_progress.setValue(event['completed'])
                self.set_inference_status(f"{text} · {event['completed']} / {event['total']} tasks complete")
            elif kind == 'memory':
                self.last_memory = text
                self.caspy.memory.setText(text)

    def stop_inference(self):
        if self.inference is not None:
            self.inference_stopped = True
            self.inference.kill()

    def inference_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.inference_failed = True
            self.set_inference_status("Could not start the local inference process.")
            self.inference_finished(1)

    def inference_finished(self, exit_code, *_):
        self.read_inference()
        self.inference.deleteLater()
        self.inference = None
        self.stop_button.setEnabled(False)
        self.caspy.memory.setText('Model unloaded.' + ('\nLast request:\n' + self.last_memory if self.last_memory else ''))
        if self.task_progress.maximum() == 0:
            self.task_progress.hide()
        if self.inference_stopped:
            self.set_inference_status("Inference stopped; model unloaded.")
        elif not self.inference_failed:
            self.set_inference_status("Answer complete; model unloaded." if exit_code == 0 else
                                         "Local inference failed. Run with uv run --locked --extra inference main.py and check model compatibility.")
        self.update_scope()

    def connect_gmail(self):
        self.start(gmail.connect)
        self.statusBar().showMessage("Complete Google sign-in in your browser (60-second timeout)…")

    def show_account(self, email):
        if email != self.email:
            self.mailbox.clear()
            self.question.clear()
        self.email = email
        self.statusBar().showMessage(
            f"Saved account: {email} · Read-only"
            if email else "Gmail is not connected."
        )
        self.refresh_messages()

    def refresh_messages(self):
        self.invalidate_answer()
        self.mail_list.clear()
        self.reader.clear()
        if self.email:
            for message in mail_store.messages(self.mailbox, self.email):
                date = datetime.fromtimestamp(message["timestamp"] / 1000).strftime("%Y-%m-%d %H:%M")
                item = QListWidgetItem(f"{date} · {message['sender']}\n{message['subject']}")
                item.setData(Qt.ItemDataRole.UserRole, message["id"])
                self.mail_list.addItem(item)
        self.update_scope()

    def read_message(self, item):
        if not item:
            self.reader.clear()
            return
        message = mail_store.message(self.mailbox, self.email, item.data(Qt.ItemDataRole.UserRole))
        if message:
            self.reader.setPlainText(
                f"Email ID: {message['id']}\nFrom: {message['sender']}\nTo: {message['recipients']}\n"
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
            first, last, self.mailbox, account,
            self.task.progress.emit, self.task.isInterruptionRequested,
        ), self.fetched)
        self.cancel_button.setEnabled(True)
        self.statusBar().showMessage("Fetching selected local times; previous emails will be replaced on success…")

    def fetched(self, result):
        self.refresh_messages()
        state = "Fetch cancelled; previous emails kept" if result["cancelled"] else "Fetch complete; previous session emails replaced"
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
        self.update_scope()

    def closeEvent(self, event):
        if self.inference is not None:
            self.stop_inference()
            self.inference.waitForFinished(3000)
        if self.caspy.task is not None:
            self.caspy.task.requestInterruption()
            self.statusBar().showMessage("Stopping model download. Close again when finished.")
            event.ignore()
            return
        if self.task is not None:
            self.task.requestInterruption()
            self.statusBar().showMessage("Stopping; waiting for the current request or sign-in timeout before closing. Close again when finished.")
            event.ignore()
        else:
            self.mailbox.clear()
            self.mail_list.clear()
            self.reader.clear()
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
