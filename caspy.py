"""Model selection only; downloading and inference come in later increments."""

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QLabel, QPushButton, QVBoxLayout, QWidget,
)


PRESET = "mlx-community/Qwen3.5-4B-MLX-4bit"


class ModelPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("Ghost-box", "Ghost-box")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Caspy"))
        layout.addWidget(QLabel("Local model"))
        self.selector = QComboBox()
        self.selector.addItem("No model selected", "")
        self.selector.addItem("Qwen3.5 · 4B · MLX 4-bit", PRESET)
        layout.addWidget(self.selector)
        choose = QPushButton("Choose local MLX folder…")
        choose.clicked.connect(self.choose_local)
        layout.addWidget(choose)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        note = QLabel("Selection only. Downloading and inference are not available yet.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

        selected = self.settings.value("model/selection", "", type=str)
        if selected and selected != PRESET:
            self.selector.addItem("Local: " + Path(selected).name, selected)
        self.selector.setCurrentIndex(max(0, self.selector.findData(selected)))
        self.selector.currentIndexChanged.connect(self.save_selection)
        self.update_status()

    def choose_local(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose local MLX model folder")
        if not folder:
            return
        # Keep just one custom folder in the small selector.
        if self.selector.count() > 2:
            self.selector.removeItem(2)
        self.selector.addItem("Local: " + Path(folder).name, folder)
        self.selector.setCurrentIndex(2)

    def save_selection(self):
        self.settings.setValue("model/selection", self.selector.currentData())
        self.update_status()

    def update_status(self):
        selected = self.selector.currentData()
        if not selected:
            text = "No model selected."
        elif selected == PRESET:
            text = PRESET + "\nPreset selected; download status has not been checked. MLX requires Apple Silicon."
        elif not Path(selected).is_dir():
            text = selected + "\nFolder is missing. Choose another folder."
        else:
            text = selected + "\nLocal folder selected; model compatibility has not been checked."
        self.status.setText(text)
