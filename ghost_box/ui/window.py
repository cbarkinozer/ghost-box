"""Ghost-box desktop window. Run with: uv run --locked main.py."""

import os
import math
import json
import platform
import time
from importlib.util import find_spec
from pathlib import Path
import stat
import sys
from datetime import datetime

from PySide6.QtCore import QDate, QDateTime, QItemSelectionModel, QLibraryInfo, QSettings, QStandardPaths, QTime, Qt
from PySide6.QtGui import QFont, QFontDatabase, QFontInfo
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QMessageBox, QPushButton,
    QToolBar, QDateTimeEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QSplitter,
    QAbstractItemView, QHBoxLayout, QVBoxLayout, QWidget,
    QProgressBar,
    QComboBox,
    QCheckBox, QTabWidget,
)

from ..mail import gmail
from ..mail import store as mail_store
from .caspy import ModelPanel
from ..mail.context import SYSTEM, SUMMARY, build_context, with_language
from .answer_view import AnswerView
from .tasks import AccountTask
from .compose import ComposeDialog
from .history import History
from .diagnostics import DiagnosticsDialog
from .work_steps import WorkSteps
from ..mail.diagnostics import safe_record
from ..mail.metadata import details
from ..models.session import ModelSession


def configure_fonts(app):
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    font.setPointSizeF(max(13, QFontInfo(font).pointSizeF()))
    app.setFont(font)


def prepare_qt_plugins():
    """Qt skips macOS-hidden plugin files, even when their path is correct."""
    if sys.platform != "darwin":
        return
    root = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    for path in (root, *root.rglob("*")):
        flags = path.stat().st_flags
        if flags & stat.UF_HIDDEN:
            os.chflags(path, flags & ~stat.UF_HIDDEN)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ghost-box")
        self.resize(1180, 820)
        self.setMinimumSize(1000, 700)
        self.task = None
        self.answer_running = False
        self.history = History()
        self.summary_mode = False
        self.last_memory = ''
        self.runtime = ModelSession(self)
        self.answer_markdown = ''
        self.answer_description = ''
        self.request_count = 0
        self.answer_question = ''
        self.answer_is_summary = False
        self.summary_cards = []
        self.diagnostic_rows = []
        self.diagnostics_dialog = None
        self.answer_elapsed = 0
        self.answer_truncated = False
        self.preferences = QSettings('Ghost-box', 'Ghost-box')
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
        toolbar.addWidget(QLabel('  Response language '))
        self.language = QComboBox()
        self.language.addItem('Türkçe', 'Turkish')
        self.language.addItem('English', 'English')
        saved_language = self.preferences.value('response_language', 'Turkish', type=str)
        self.language.setCurrentIndex(max(0, self.language.findData(saved_language)))
        self.language.setToolTip('Default language for answers and summaries. Explicit language instructions can override it.')
        toolbar.addWidget(self.language)
        diagnostics_button = QPushButton('Diagnostics')
        diagnostics_button.setToolTip('Content-free summary failure reasons and timings, kept only in RAM.')
        diagnostics_button.clicked.connect(self.show_diagnostics)
        toolbar.addWidget(diagnostics_button)
        self.model_toggle = QPushButton('👻 Caspy')
        self.model_toggle.setCheckable(True)
        self.model_toggle.setChecked(True)
        toolbar.addWidget(self.model_toggle)

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
        self.skip_promotions = QCheckBox('Skip Promotions')
        self.skip_promotions.setChecked(self.preferences.value('skip_promotions', True, type=bool))
        self.skip_promotions.setToolTip('Exclude mail categorized by Gmail as Promotions. Other categories and Sent remain included.')
        self.skip_promotions.toggled.connect(lambda value: self.preferences.setValue('skip_promotions', value))
        dates.addWidget(self.skip_promotions)

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
        reading_font = QFont(QApplication.font())
        reading_font.setPointSizeF(max(14, QFontInfo(reading_font).pointSizeF()))
        self.reader.setFont(reading_font)
        self.reader.setReadOnly(True)
        self.reader.setPlaceholderText("Fetch today's mail, then select a message.\nTimes are local. Each successful fetch replaces this account's previous session emails.\nMail is held in memory only and disappears when you close the app.\nSent mail is included; Spam, Trash, and Drafts are excluded.")
        reading_panel = QWidget()
        reading_panel.setMinimumWidth(420)
        reading_layout = QVBoxLayout(reading_panel)
        reading_layout.setContentsMargins(0, 0, 0, 0)
        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        reply_actions = QHBoxLayout()
        self.preview_toggle = QPushButton('Email preview ▸')
        self.preview_toggle.setCheckable(True)
        self.preview_toggle.setChecked(False)
        self.reader.hide()
        self.preview_toggle.toggled.connect(self.reader.setVisible)
        self.preview_toggle.toggled.connect(lambda visible: self.preview_toggle.setText('Email preview ▾' if visible else 'Email preview ▸'))
        reply_actions.addWidget(self.preview_toggle)
        reply_actions.addStretch()
        self.preview_actions = []
        for label, mode in (('Reply', 'reply'), ('Reply all', 'reply_all'), ('Forward', 'forward')):
            button = QPushButton(label)
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, action=mode: self.compose_current(action))
            reply_actions.addWidget(button)
            self.preview_actions.append(button)
        preview_layout.addLayout(reply_actions)
        preview_layout.addWidget(self.reader)
        preview.setMinimumHeight(0)
        conversation = QWidget()
        conversation.setMinimumHeight(230)
        conversation_layout = QVBoxLayout(conversation)
        history_row = QHBoxLayout()
        self.session_picker = QComboBox()
        self.session_picker.setMinimumContentsLength(12)
        self.session_picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.session_picker.setPlaceholderText('Sessions · RAM only')
        self.session_picker.setToolTip('Ask emails or Summarize starts a session. All sessions stay in RAM until cleared or closed.')
        self.message_picker = QComboBox()
        self.message_picker.setMinimumContentsLength(12)
        self.message_picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.message_picker.setPlaceholderText('Messages')
        self.message_picker.setToolTip('Revisit a message. Follow up continues the displayed message, not the whole transcript.')
        self.session_picker.currentIndexChanged.connect(self.select_session)
        self.message_picker.currentIndexChanged.connect(self.select_history_message)
        history_row.addWidget(self.session_picker, 1)
        history_row.addWidget(self.message_picker, 1)
        self.clear_sessions = QPushButton('Clear sessions')
        self.clear_sessions.clicked.connect(self.clear_history)
        history_row.addWidget(self.clear_sessions)
        conversation_layout.addLayout(history_row)
        self.scope_label = QLabel()
        self.scope_label.setWordWrap(True)
        self.scope_label.setToolTip("Includes selected email headers, question, and instructions. Approximately 4 characters per token; actual token counts vary.")
        scope_row = QHBoxLayout()
        scope_row.addWidget(self.scope_label, 1)
        self.question = QPlainTextEdit()
        self.question.setFont(reading_font)
        self.question.setPlaceholderText("Question for Ask, or optional instructions for Summarize…")
        self.question.setMaximumHeight(56)
        self.question.textChanged.connect(self.scope_changed)
        self.search_enabled = QCheckBox('Use BM25 search for questions')
        self.search_enabled.setToolTip('For Ask emails: one extra call searches selected mail and supplies only matching excerpts. Follow up chooses a local lookup only when needed. Summarize reads all selected mail.')
        scope_row.addWidget(self.search_enabled)
        conversation_layout.addLayout(scope_row)
        actions = QHBoxLayout()
        self.ask_button = QPushButton("Ask emails")
        self.ask_button.clicked.connect(self.ask_selected)
        actions.addWidget(self.ask_button)
        self.summary_button = QPushButton('Summarize')
        self.summary_button.setToolTip('Summarize selected emails. Text above is used as additional instructions; it stays in RAM.')
        self.summary_button.clicked.connect(lambda: self.ask_selected(summarize=True))
        actions.addWidget(self.summary_button)
        self.followup_button = QPushButton('Follow up')
        self.followup_button.setToolTip('Continue the displayed message, not the full mailbox. Original mail is read only if the model requests one local lookup. Click to focus the input.')
        self.followup_button.clicked.connect(lambda: self.ask_selected(follow_up=True))
        actions.addWidget(self.followup_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_inference)
        actions.addWidget(self.stop_button)
        self.inference_status = QLabel("Select emails and enter a question to begin.")
        self.inference_status.setWordWrap(True)
        self.inference_status.setTextFormat(Qt.TextFormat.PlainText)
        conversation_layout.addWidget(self.inference_status)
        self.search_status = QLabel()
        self.search_status.setWordWrap(True)
        self.search_status.setTextFormat(Qt.TextFormat.PlainText)
        self.search_status.hide()
        conversation_layout.addWidget(self.search_status)
        self.task_progress = QProgressBar()
        self.task_progress.setFormat('%v / %m LLM calls complete')
        self.task_progress.hide()
        conversation_layout.addWidget(self.task_progress)
        self.work_steps = WorkSteps()
        self.answer_scope = QLabel()
        self.answer_scope.setWordWrap(True)
        self.answer_scope.setTextFormat(Qt.TextFormat.PlainText)
        conversation_layout.addWidget(self.answer_scope)
        self.answer = AnswerView()
        self.answer.setFont(reading_font)
        self.answer.document().setDefaultFont(reading_font)
        self.answer.setMinimumHeight(120)
        self.answer.source_clicked.connect(self.preview_source)
        self.answer.compose_clicked.connect(self.open_composer)
        self.answer.setPlaceholderText("Answers stay in RAM. Select multiple emails with Cmd/Ctrl-click or Shift-click.")
        self.output_tabs = QTabWidget()
        self.output_tabs.addTab(self.answer, 'Answer')
        self.output_tabs.addTab(self.work_steps, 'Work steps')
        self.work_steps.changed.connect(self.steps_changed)
        conversation_layout.addWidget(self.output_tabs, 1)
        conversation_layout.addWidget(self.question)
        conversation_layout.addLayout(actions)
        reading_split = QSplitter(Qt.Orientation.Vertical)
        self.reading_split = reading_split
        reading_split.setChildrenCollapsible(False)
        reading_split.addWidget(preview)
        reading_split.addWidget(conversation)
        reading_split.setSizes([48, 640])
        self.preview_toggle.toggled.connect(lambda visible: reading_split.setSizes([140, 540] if visible else [38, 640]))
        reading_layout.addWidget(reading_split)
        content = QSplitter()
        content.setChildrenCollapsible(False)
        content.addWidget(mail_panel)
        content.addWidget(reading_panel)
        self.caspy = ModelPanel()
        self.caspy.setMinimumWidth(240)
        self.caspy.setMaximumWidth(280)
        self.model_toggle.toggled.connect(self.caspy.setVisible)
        self.caspy.selector.currentIndexChanged.connect(self.model_selection_changed)
        self.caspy.parameters_changed.connect(self.scope_changed)
        self.caspy.load_button.clicked.connect(self.load_model)
        self.caspy.unload_button.clicked.connect(lambda: self.runtime.unload())
        self.runtime.event.connect(self.inference_event)
        self.runtime.state_changed.connect(self.model_state_changed)
        content.addWidget(self.caspy)
        content.setSizes([280, 640, 260])
        content.setStretchFactor(0, 0)
        content.setStretchFactor(1, 1)
        content.setStretchFactor(2, 0)
        self.setCentralWidget(content)
        self.language.currentIndexChanged.connect(self.language_changed)
        self.model_state_changed()
        self.scope_changed()
        self.start(gmail.saved_account)

    def start(self, operation, success=None):
        self.save_history_message()
        if self.answer_running:
            self.stop_inference()
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self.fetch_button.setEnabled(False)
        self.first.setEnabled(False)
        self.last.setEnabled(False)
        self.skip_promotions.setEnabled(False)
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
                                   and self.task is None and not self.answer_running and not self.runtime.busy and self.runtime.state != 'unloading')
        self.summary_button.setEnabled(bool(messages) and self.task is None and not self.answer_running and not self.runtime.busy and self.runtime.state != 'unloading')
        self.followup_button.setEnabled(bool(self.answer_markdown and self.answer.sources)
                                        and self.task is None and not self.answer_running and not self.runtime.busy and self.runtime.state != 'unloading')
        for button in self.preview_actions:
            button.setEnabled(bool(self.mail_list.currentItem() and self.email) and self.task is None)
        for control in (self.session_picker, self.message_picker, self.clear_sessions):
            control.setEnabled(not self.answer_running and not self.runtime.busy and self.task is None)
        self.update_model_buttons()
        if self.answer_description:
            changed = {message['id'] for message in messages} != set(self.answer.sources)
            calls = f' · LLM calls: {self.request_count}'
            calls += f' · {self.answer_elapsed:.1f} s' if self.answer_elapsed else ''
            calls += ' · partial' if self.answer_truncated else ''
            self.answer_scope.setText(self.answer_description + calls + (' · selection changed' if changed else ''))
            self.answer_scope.setToolTip('This answer keeps its original email snapshot. The current selection is used only for the next request.')

    def question_text(self):
        text = self.question.toPlainText().strip()
        question = SUMMARY + ('\nAdditional instructions: ' + text if text else '') if self.summary_mode else text
        return with_language(question, self.language.currentData())

    def language_changed(self):
        self.preferences.setValue('response_language', self.language.currentData())
        self.scope_changed()

    def scope_changed(self):
        self.summary_mode = False
        self.update_scope()
        if not self.answer_running and not self.answer.toPlainText():
            self.inference_status.setText(
                "Ready to ask or summarize selected emails." if self.ask_button.isEnabled()
                else "Enter a question, or press Summarize." if self.summary_button.isEnabled()
                else "Select emails to begin."
            )

    def set_inference_status(self, text):
        self.inference_status.setText(text)
        self.statusBar().showMessage(text)

    def steps_changed(self):
        self.output_tabs.setTabText(1, self.work_steps.title)

    def refresh_diagnostics(self):
        if self.diagnostics_dialog is not None:
            self.diagnostics_dialog.refresh(self.diagnostic_rows)

    def show_diagnostics(self):
        if self.diagnostics_dialog is not None:
            self.diagnostics_dialog.raise_()
            self.diagnostics_dialog.activateWindow()
            return
        dialog = DiagnosticsDialog(self)
        self.diagnostics_dialog = dialog
        dialog.refresh(self.diagnostic_rows)
        def closed():
            dialog.text.clear()
            self.diagnostics_dialog = None
            dialog.deleteLater()
        dialog.finished.connect(closed)
        dialog.open()

    def invalidate_answer(self):
        if self.answer_running:
            self.stop_inference()
        self.answer.clear()
        self.answer_markdown = ''
        self.answer_description = ''
        self.request_count = 0
        self.answer_question = ''
        self.answer_is_summary = False
        self.summary_cards = []
        self.diagnostic_rows = []
        self.refresh_diagnostics()
        self.answer_elapsed = 0
        self.answer_truncated = False
        self.search_status.clear()
        self.search_status.hide()
        self.answer_scope.clear()
        self.task_progress.hide()
        self.work_steps.restore([], self.language.currentData())

    def save_history_message(self):
        if self.history.current is not None:
            self.history.current.update(
                markdown=self.answer_markdown, description=self.answer_description,
                question=self.answer_question, summary=self.answer_is_summary,
                cards=self.summary_cards, elapsed=self.answer_elapsed,
                truncated=self.answer_truncated, requests=self.request_count,
                sources=dict(self.answer.sources), diagnostics=list(self.diagnostic_rows),
                steps=[dict(row) for row in self.work_steps.rows], steps_language=self.work_steps.language, steps_error=self.work_steps.error_text,
                search_status=self.search_status.text())

    def refresh_history_controls(self):
        self.session_picker.blockSignals(True)
        self.message_picker.blockSignals(True)
        self.session_picker.clear()
        for index, session in enumerate(self.history.sessions, 1):
            self.session_picker.addItem(f'{index}. {session["title"]}')
        self.session_picker.setCurrentIndex(self.history.session)
        self.message_picker.clear()
        if self.history.session >= 0:
            for index, message in enumerate(self.history.sessions[self.history.session]['messages'], 1):
                self.message_picker.addItem(f'{index}. {message["question"][:65]}')
            self.message_picker.setCurrentIndex(self.history.message)
        self.session_picker.blockSignals(False)
        self.message_picker.blockSignals(False)

    def display_history_message(self):
        record = self.history.current
        if record is None:
            return
        self.answer_markdown = record['markdown']
        self.answer_description = record['description']
        self.answer_question = record['question']
        self.answer_is_summary = record['summary']
        self.summary_cards = record['cards']
        self.diagnostic_rows = list(record.get('diagnostics', []))
        self.refresh_diagnostics()
        self.answer_elapsed = record['elapsed']
        self.answer_truncated = record['truncated']
        self.request_count = record['requests']
        self.answer.sources = dict(record['sources'])
        self.work_steps.restore(record.get('steps', []), record.get('steps_language', 'English'), record.get('steps_error', ''))
        self.answer.render(self.answer_markdown, link_citations=not self.answer_is_summary)
        self.output_tabs.setCurrentIndex(0)
        self.search_status.setText(record.get('search_status', ''))
        self.search_status.setVisible(bool(self.search_status.text()))
        self.task_progress.hide()
        self.set_inference_status('Session message · RAM only')
        self.refresh_history_controls()
        self.update_scope()

    def select_session(self, index):
        if index < 0 or self.answer_running:
            return
        self.save_history_message()
        self.history.select(index)
        self.display_history_message()

    def select_history_message(self, index):
        if index < 0 or self.history.session < 0 or self.answer_running:
            return
        self.save_history_message()
        self.history.select(self.history.session, index)
        self.display_history_message()

    def clear_history(self, checked=False, force=False):
        if self.answer_running:
            if not force:
                return
            self.stop_inference()
            self.answer_running = False
            self.stop_button.setEnabled(False)
        self.history.clear()
        self.invalidate_answer()
        self.read_message(self.mail_list.currentItem())
        self.refresh_history_controls()
        self.update_scope()

    def preview_source(self, identifier):
        self.preview_toggle.setChecked(True)
        for row in range(self.mail_list.count()):
            item = self.mail_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == identifier:
                # Navigation must not change the selection used by the next question.
                self.mail_list.setCurrentItem(item, QItemSelectionModel.SelectionFlag.NoUpdate)
                self.mail_list.scrollToItem(item)
                self.read_message(item)
                return
        message = self.answer.sources.get(identifier)
        if message:
            self.reader.setPlainText(f"Email ID: {identifier}\nFrom: {message['sender']}\n"
                                     f"Subject: {message['subject']}\n\n{message['body']}")
            self.statusBar().showMessage('Source from this conversation’s RAM snapshot.')

    def compose_current(self, mode):
        item = self.mail_list.currentItem()
        if item:
            self.open_composer(item.data(Qt.ItemDataRole.UserRole), mode)

    def open_composer(self, identifier, mode):
        if not self.email or self.task is not None:
            self.statusBar().showMessage('Wait for the account operation and connect Gmail before composing.')
            return
        source = mail_store.message(self.mailbox, self.email, identifier)
        if source is None:
            source = self.answer.sources.get(identifier)
        if source is None:
            self.statusBar().showMessage('This source is no longer in the current mail session.')
            return
        try:
            dialog = ComposeDialog(source, self.email, mode, self)
        except ValueError as error:
            QMessageBox.warning(self, 'Compose', str(error))
            return
        dialog.exec()
        dialog.deleteLater()

    def model_configuration(self):
        folder = self.caspy.selected_folder()
        if folder is None:
            self.set_inference_status('Select a downloaded preset or a local model first.')
            return None
        is_gguf = folder.suffix.lower() == '.gguf'
        if not is_gguf and (sys.platform != 'darwin' or platform.machine() != 'arm64'):
            self.set_inference_status('MLX requires Apple Silicon macOS.')
            return None
        if find_spec('llama_cpp' if is_gguf else 'mlx_lm') is None:
            extra = 'gguf' if is_gguf else 'inference'
            self.set_inference_status(f'Local runtime is missing. Restart with: uv run --locked --extra {extra} main.py')
            return None
        try:
            return folder, self.caspy.parameters()
        except ValueError as error:
            self.set_inference_status(str(error))
            return None

    def update_model_buttons(self):
        folder = self.caspy.selected_folder()
        try:
            params = self.caspy.parameters()
        except ValueError:
            params = None
        matches = self.runtime.matches(folder, params)
        self.caspy.load_button.setText('Loaded' if matches and self.runtime.state == 'ready' else
                                       'Reload' if self.runtime.process is not None else 'Load')
        self.caspy.load_button.setEnabled(folder is not None and not self.answer_running
                                         and not self.runtime.busy
                                         and self.runtime.state not in ('loading', 'unloading')
                                         and not (matches and self.runtime.state == 'ready'))
        self.caspy.unload_button.setEnabled(self.runtime.process is not None
                                           and not self.answer_running and not self.runtime.busy and self.runtime.state != 'unloading')

    def load_model(self):
        configuration = self.model_configuration()
        if configuration is not None and not self.answer_running and not self.runtime.busy:
            self.runtime.load(*configuration)

    def model_selection_changed(self):
        self.runtime.unload('Model selection changed')
        self.scope_changed()

    def model_state_changed(self, *_):
        state = self.runtime.state
        folder = self.runtime.folder
        name = ('Qwen3.5 4B · MLX' if folder == self.caspy.model_folder else
               'Qwen3.5 4B · GGUF' if folder and folder.parent == self.caspy.gguf_folder else folder.name if folder else '')
        descriptions = {'unloaded': 'Model: unloaded', 'loading': f'Loading: {name}',
                        'ready': f'Loaded: {name}\nIdle · auto-unload after 5 min',
                        'generating': f'Loaded: {name} · generating', 'unloading': f'Unloading: {name}'}
        self.caspy.model_state.setText(descriptions[state])
        if state == 'loading':
            self.last_memory = ''
            self.caspy.memory.setText('Loading model; measuring memory…')
        elif state == 'unloaded':
            self.caspy.memory.setText('Last session:\n' + self.last_memory if self.last_memory else 'No memory measurement available.')
            if self.runtime.reason and not self.answer_running:
                message = 'Model unloaded after five idle minutes.' if self.runtime.reason == 'Five minutes idle' else 'Model unloaded.'
                self.set_inference_status(message + (' Answer kept.' if self.answer.toPlainText() else ''))
        self.update_scope()

    def ask_selected(self, summarize=False, follow_up=False):
        if self.answer_running or self.runtime.busy or self.task is not None or self.runtime.state == 'unloading':
            return
        self.summary_mode = summarize
        if follow_up and not self.question.toPlainText().strip():
            self.question.setFocus()
            self.set_inference_status('Type your follow-up question above, then press Follow up.')
            return
        messages = list(self.answer.sources.values()) if follow_up else self.selected_messages()
        if not messages or (not summarize and not self.question.toPlainText().strip()):
            self.set_inference_status('Select emails and enter a question, or press Summarize.')
            return
        configuration = self.model_configuration()
        if configuration is None:
            return
        question = self.question_text()
        previous = None
        if follow_up:
            previous_answer = self.answer_markdown
            if self.answer_is_summary and self.summary_cards:
                # Keep only summary findings, not duplicated overview, quotes, headers
                # and compose links. Original text is available through scoped tools.
                previous_answer = json.dumps([
                    {'source': card['source'], 'subject': self.answer.sources[card['id']]['subject'],
                     'kind': card['kind'], 'facts': [fact['text'] for fact in card['facts']]}
                    for card in self.summary_cards], ensure_ascii=False)
            previous = {'request': self.answer_question, 'answer': previous_answer,
                        'partial': self.answer_truncated}
        self.save_history_message()
        self.answer_question = self.question.toPlainText().strip() or SUMMARY
        self.answer_is_summary = summarize
        self.summary_cards = []
        self.diagnostic_rows = []
        self.refresh_diagnostics()
        self.answer.clear()
        self.answer_markdown = ''
        self.request_count = 0
        self.answer_elapsed = 0
        self.answer_truncated = False
        self.preview_toggle.setChecked(False)
        self.output_tabs.setCurrentIndex(0)
        self.answer_started = time.monotonic()
        self.answer.sources = {message['id']: message.copy() for message in messages}
        count = len(self.answer.sources)
        self.answer_description = f"{'Follow-up' if follow_up else 'Summary' if summarize else 'Answer'} · {count} {'email' if count == 1 else 'emails'} · {self.language.currentText()}"
        self.work_steps.restore([], self.language.currentData())
        self.search_status.clear()
        self.history.append({'question': self.answer_question}, new_session=not follow_up)
        self.save_history_message()
        self.refresh_history_controls()
        self.inference_failed = False
        self.inference_warning = ''
        self.answer_running = True
        self.stop_button.setEnabled(True)
        self.task_progress.setRange(0, 0)
        self.task_progress.show()
        self.search_status.clear()
        self.search_status.hide()
        self.set_inference_status('Preparing local answer…')
        self.update_scope()
        request = {'emails': messages, 'question': question,
                   'summarize': summarize,
                   'account': self.email, 'language': self.language.currentData(),
                   'use_search': self.search_enabled.isChecked() and not summarize and not follow_up,
                   'follow_up': follow_up, 'previous': previous}
        self.question.clear()
        self.runtime.load(*configuration, request=request)

    def inference_event(self, event):
        kind, text = event.get('kind'), event.get('text', '')
        if kind == 'step' and self.answer_running:
            self.work_steps.update_step(event)
        elif kind == 'diagnostic' and self.answer_running:
            record = safe_record(event)
            if record is not None:
                self.diagnostic_rows.append(record)
                self.diagnostic_rows = self.diagnostic_rows[-512:]
                self.refresh_diagnostics()
        elif kind == 'summary' and self.answer_running:
            self.summary_cards = event['cards']
            self.answer_markdown = event['markdown']
            self.answer.render(self.answer_markdown, link_citations=False, scroll_to_top=event.get('complete', False))
        elif kind == 'text' and self.answer_running:
            self.answer_markdown += text
            cursor = self.answer.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(text)
            self.answer.setTextCursor(cursor)
        elif kind in ('status', 'error', 'warning'):
            if self.answer_running:
                if kind == 'error':
                    self.inference_failed = True
                    self.work_steps.error_text = text
                elif kind == 'warning':
                    self.inference_warning = text
                    self.answer_truncated = True
            self.set_inference_status(text)
        elif kind == 'progress' and self.answer_running:
            self.task_progress.setRange(0, event['total'])
            self.task_progress.setValue(event['completed'])
            self.set_inference_status(f"{text} · {event['completed']} / {event['total']} tasks complete")
        elif kind == 'memory':
            self.last_memory = text
            self.caspy.memory.setText(text)
        elif kind == 'requests' and self.answer_running:
            self.request_count = event['count']
            self.update_scope()
        elif kind == 'search' and self.answer_running:
            self.search_status.setText(text)
            self.search_status.show()
        elif kind == 'done' and self.answer_running:
            self.finish_answer(event)
        elif kind == 'ready' and not self.answer_running:
            self.set_inference_status('Model loaded. Ready to ask; auto-unloads after five idle minutes.')

    def stop_inference(self):
        if self.answer_running:
            self.runtime.unload('Stopped by user')

    def finish_answer(self, event):
        self.answer_running = False
        self.work_steps.finish(event.get('status', 'error'))
        self.answer_elapsed = time.monotonic() - self.answer_started
        self.answer_truncated |= event.get('truncated', False) or event.get('status') in ('stopped', 'error')
        self.answer.render(self.answer_markdown, link_citations=not self.answer_is_summary)
        self.stop_button.setEnabled(False)
        if self.task_progress.maximum() == 0:
            self.task_progress.hide()
        if event.get('status') == 'stopped':
            self.set_inference_status('Inference stopped; model unloaded. Partial answer kept.')
        elif self.inference_warning:
            self.set_inference_status(self.inference_warning)
        elif event.get('status') == 'success' and not self.inference_failed:
            completed, total = self.task_progress.value(), self.task_progress.maximum()
            self.task_progress.hide()
            self.set_inference_status(f'Answer complete · {completed}/{total} tasks · model remains loaded.')
        elif not self.inference_failed:
            self.set_inference_status('Inference failed; any partial answer is incomplete.')
        self.set_inference_status(self.inference_status.text() + f' · {self.answer_elapsed:.1f} s')
        self.save_history_message()
        self.update_scope()

    def connect_gmail(self):
        self.start(gmail.connect)
        self.statusBar().showMessage("Complete Google sign-in in your browser (60-second timeout)…")

    def show_account(self, email):
        if email != self.email:
            self.clear_history(force=True)
            self.mailbox.clear()
            self.question.clear()
        self.email = email
        self.statusBar().showMessage(
            f"Saved account: {email} · Fetch on demand"
            if email else "Gmail is not connected."
        )
        self.refresh_messages()

    def refresh_messages(self):
        self.save_history_message()
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
        for button in self.preview_actions:
            button.setEnabled(bool(item and self.email) and self.task is None)
        if not item:
            self.reader.clear()
            return
        message = mail_store.message(self.mailbox, self.email, item.data(Qt.ItemDataRole.UserRole))
        if message:
            self.preview_toggle.setChecked(True)
            meta = details(message, self.email)
            self.reader.setPlainText(
                f"Email ID: {message['id']}\nFrom: {message['sender']}\nTo: {message['recipients']}\n"
                f"CC: {message.get('cc', '')}\nRole: {meta['role']} · To: {meta['to_count']} · CC: {meta['cc_count']} · Attachments: {meta['attachment_count']}\n"
                f"Subject: {message['subject']}\n\n{message['body']}"
            )

    def fetch_mail(self):
        first = self.first.dateTime().toPython()
        last = self.last.dateTime().toPython()
        if first > last:
            QMessageBox.warning(self, "Date range", "From must be on or before To.")
            return
        account = self.email
        exclude_promotions = self.skip_promotions.isChecked()
        self.start(lambda: gmail.fetch(
            first, last, self.mailbox, account,
            self.task.progress.emit, self.task.isInterruptionRequested,
            exclude_promotions=exclude_promotions,
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
        self.skip_promotions.setEnabled(True)
        self.task.deleteLater()
        self.task = None
        self.update_scope()

    def closeEvent(self, event):
        self.runtime.unload('Window closing')
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
            self.runtime.shutdown()
            self.history.clear()
            self.refresh_history_controls()
            self.mailbox.clear()
            self.mail_list.clear()
            self.reader.clear()
            self.question.clear()
            self.invalidate_answer()
            event.accept()


def main() -> int:
    prepare_qt_plugins()
    app = QApplication(sys.argv)
    app.setApplicationName("Ghost-box")
    configure_fonts(app)

    window = Window()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
