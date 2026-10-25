"""Optional RAM-only numeric diagnostics; no raw email or model-output viewer."""

from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout

from ..mail.diagnostics import report


class DiagnosticsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Summary diagnostics · RAM only')
        self.resize(850, 450)
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text)
        actions = QHBoxLayout()
        copy = QPushButton('Copy content-free diagnostics')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text.toPlainText()))
        actions.addWidget(copy)
        actions.addStretch()
        close = QPushButton('Close')
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        layout.addLayout(actions)

    def refresh(self, records):
        scroll = self.text.verticalScrollBar()
        position, at_end = scroll.value(), scroll.value() == scroll.maximum()
        self.text.setPlainText(report(records))
        scroll.setValue(scroll.maximum() if at_end else position)
