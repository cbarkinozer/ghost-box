"""Human-reviewed reply/forward dialog. Drafts and approved payloads stay in RAM."""

import json
import time
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from ..mail import gmail
from ..mail.drafting import prepare, draft_prompt, build_payload
from .tasks import AccountTask


class ComposeDialog(QDialog):
    def __init__(self, source, account, mode, owner):
        super().__init__(owner)
        self.owner, self.source, self.account, self.mode = owner, source.copy(), account, mode
        self.task = None
        self.generating = False
        self.allowed = False
        self.locked = False
        self.sending = False
        self.cleaned = False
        self.warning = ''
        self.setWindowTitle({'reply': 'Reply', 'reply_all': 'Reply all', 'forward': 'Forward'}[mode])
        self.resize(760, 720)
        values = prepare(source, account, mode)
        self.forwarded = values['body'].replace('\r\n', '\n').replace('\r', '\n') if mode == 'forward' else ''
        layout = QVBoxLayout(self)
        heading = QLabel(f'From: {account}\nSource: {source["subject"]}')
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        form = QFormLayout()
        self.to = QLineEdit(values['to']); self.cc = QLineEdit(values['cc'])
        self.subject = QLineEdit(values['subject'])
        form.addRow('To', self.to); form.addRow('CC', self.cc); form.addRow('Subject', self.subject)
        layout.addLayout(form)
        self.instructions = QPlainTextEdit()
        self.instructions.setPlaceholderText('What should the reply say? Or how should the existing draft be rewritten?')
        self.instructions.setMaximumHeight(80)
        layout.addWidget(self.instructions)
        actions = QHBoxLayout()
        self.generate_button = QPushButton('Prepare / rewrite draft')
        self.generate_button.clicked.connect(self.generate)
        actions.addWidget(self.generate_button)
        self.permission_button = QPushButton('Enable Gmail sending')
        self.permission_button.clicked.connect(self.enable_sending)
        actions.addWidget(self.permission_button)
        layout.addLayout(actions)
        self.body = QPlainTextEdit(values['body'])
        self.body.setFont(owner.reader.font())
        self.body.textChanged.connect(self.update_buttons)
        layout.addWidget(self.body, 1)
        self.status = QLabel('Drafts stay in RAM. Nothing is sent until you review and confirm Send.')
        self.status.setWordWrap(True); self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        if mode == 'forward':
            note = QLabel('Forward includes text only; original attachments are not included.')
            note.setWordWrap(True); layout.addWidget(note)
        footer = QHBoxLayout()
        copy = QPushButton('Copy text')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.body.toPlainText()))
        footer.addWidget(copy)
        self.send_button = QPushButton('Review and Send…')
        self.send_button.clicked.connect(self.review_send)
        footer.addWidget(self.send_button)
        close = QPushButton('Close'); close.clicked.connect(self.reject); footer.addWidget(close)
        layout.addLayout(footer)
        owner.runtime.event.connect(self.model_event)
        owner.runtime.state_changed.connect(self.update_buttons)
        self.start_task(lambda: gmail.can_send(account), self.permission_checked)

    def update_buttons(self, *_):
        busy = self.task is not None or self.generating
        self.generate_button.setEnabled(not busy and not self.owner.runtime.busy
                                        and self.owner.runtime.state != 'unloading' and not self.locked)
        self.permission_button.setEnabled(not busy and not self.locked)
        self.send_button.setEnabled(not busy and self.allowed and bool(self.body.toPlainText().strip()) and not self.locked)
        for field in (self.to, self.cc, self.subject, self.instructions):
            field.setEnabled(not busy and not self.locked)
        self.body.setReadOnly(busy or self.locked)

    def start_task(self, operation, success):
        self.task = AccountTask(operation, self)
        self.task.succeeded.connect(success)
        self.task.failed.connect(self.task_error)
        self.task.finished.connect(self.task_finished)
        self.update_buttons()
        self.task.start()

    def task_error(self, text):
        if self.sending:
            self.locked = True
            text = 'Send result is unconfirmed. Check Gmail Sent before sending again.'
        self.status.setText(text)

    def task_finished(self):
        self.task.deleteLater(); self.task = None
        self.sending = False
        self.update_buttons()

    def permission_checked(self, allowed):
        self.allowed = allowed
        self.permission_button.setText('Reauthorize sending' if allowed else 'Enable Gmail sending')
        self.status.setText('Sending enabled; review recipients and body before Send.' if allowed else
                            'Draft locally or enable Gmail sending to send from this dialog.')

    def enable_sending(self):
        self.status.setText('Grant sending access in your browser using the same Gmail account…')
        self.start_task(lambda: gmail.connect(allow_send=True, expected_account=self.account),
                        lambda _: self.permission_checked(True))

    def generate(self):
        if self.task is not None or self.generating or self.owner.runtime.busy or self.owner.runtime.state == 'unloading' or self.locked:
            return
        instruction = self.instructions.toPlainText().strip()
        if not instruction:
            self.instructions.setFocus(); self.status.setText('Enter what the reply should say first.'); return
        configuration = self.owner.model_configuration()
        if configuration is None:
            self.status.setText(self.owner.inference_status.text()); return
        current = self.body.toPlainText()
        if self.mode == 'forward' and self.forwarded and current.endswith(self.forwarded):
            current = current[:-len(self.forwarded)]
        question = draft_prompt(self.source, instruction, self.owner.language.currentData(), self.mode)
        question += '\nCurrent editable draft (context):\n' + json.dumps(current, ensure_ascii=False)
        self.generating = True; self.warning = ''
        self.draft_started = time.monotonic()
        self.body.clear(); self.update_buttons()
        self.status.setText('Preparing a local draft; review it before sending.')
        self.owner.runtime.load(*configuration, request={'draft': True, 'emails': [], 'question': question,
                                                       'language': self.owner.language.currentData()})

    def model_event(self, event):
        if not self.generating:
            return
        kind = event.get('kind')
        if kind == 'text':
            cursor = self.body.textCursor(); cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(event['text']); self.body.setTextCursor(cursor)
        elif kind in ('status', 'error', 'warning'):
            self.status.setText(event.get('text', ''))
            if kind in ('error', 'warning'):
                self.warning = event.get('text', '')
        elif kind == 'done':
            self.generating = False
            if self.mode == 'forward' and event.get('status') == 'success':
                self.body.appendPlainText(self.forwarded)
            self.status.setText(self.warning or ('Draft ready. Review recipients and text; edit freely.'
                                if event.get('status') == 'success' else 'Draft interrupted; inspect any partial text.'))
            self.status.setText(self.status.text() + f' · {time.monotonic() - self.draft_started:.1f} s')
            self.update_buttons()

    def review_send(self):
        if self.task is not None or self.generating or self.locked or not self.allowed:
            return
        draft = dict(to=self.to.text(), cc=self.cc.text(), subject=self.subject.text(), body=self.body.toPlainText())
        try:
            payload = build_payload(self.account, self.source, self.mode, draft)
        except ValueError as error:
            self.status.setText(str(error)); return
        approval = QMessageBox(self)
        approval.setWindowTitle('Confirm email sending')
        approval.setTextFormat(Qt.TextFormat.PlainText)
        approval.setText(f'From: {self.account}\nTo: {draft["to"]}\nCC: {draft["cc"] or "—"}\nSubject: {draft["subject"]}\n\nSend the reviewed message now?')
        approval.setDetailedText(draft['body'])
        approval.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        approval.button(QMessageBox.StandardButton.Yes).setText('Send')
        approval.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if approval.exec() != QMessageBox.StandardButton.Yes:
            return
        # Capture the approved MIME payload; later edits/model events cannot alter it.
        self.status.setText('Sending approved message…')
        self.sending = True
        def send():
            try:
                return {'id': gmail.send(self.account, payload)}
            except gmail.AccountError as error:
                return {'error': str(error), 'uncertain': getattr(error, 'uncertain', False)}
        self.start_task(send, self.sent)

    def sent(self, result):
        if 'id' in result:
            self.locked = True
            self.status.setText('Sent successfully. No automatic follow-up or additional send will occur.')
        else:
            self.locked = result.get('uncertain', False)
            self.status.setText(result['error'])

    def can_close(self):
        if self.task is not None:
            self.status.setText('Wait for the current authorization/send operation before closing.')
            return False
        return True

    def cleanup(self):
        if self.cleaned:
            return
        self.cleaned = True
        if self.generating:
            self.owner.runtime.unload('Draft dialog closed')
            self.generating = False
        self.owner.runtime.event.disconnect(self.model_event)
        self.owner.runtime.state_changed.disconnect(self.update_buttons)
        self.body.clear(); self.instructions.clear(); self.source.clear(); self.forwarded = ''
        self.to.clear(); self.cc.clear(); self.subject.clear()

    def reject(self):
        if self.can_close():
            self.cleanup()
            super().reject()

    def closeEvent(self, event):
        if not self.can_close():
            event.ignore(); return
        self.cleanup()
        super().closeEvent(event)
