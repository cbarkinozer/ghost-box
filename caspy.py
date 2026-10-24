"""Small model-selection panel and on-demand preset download."""

from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QLabel, QPushButton, QVBoxLayout, QWidget,
    QDoubleSpinBox, QSpinBox, QFormLayout, QScrollArea,
)

import model_download
import inference_settings
from model_download import PRESET


class DownloadTask(QThread):
    progress = Signal(str)
    outcome = Signal(str)

    def __init__(self, folder, parent):
        super().__init__(parent)
        self.folder = folder

    def run(self):
        try:
            model_download.download(self.folder, self.progress.emit, self.isInterruptionRequested)
            self.outcome.emit("Download complete. Model is available locally.")
        except model_download.DownloadCancelled:
            self.outcome.emit("Download cancelled. Completed files are kept for retry.")
        except Exception as error:
            if isinstance(error, OSError) and error.errno == 28:
                detail = "Disk is full."
            else:
                detail = "Check free disk space, folder permissions, and your connection."
            self.outcome.emit(f"Download failed. {detail} Retry to reuse verified files.")


class ModelPanel(QWidget):
    parameters_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("Ghost-box", "Ghost-box")
        self.task = None
        self.model_folder = Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )) / "models" / model_download.REVISION
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>👻 Caspy</b>"))
        layout.addWidget(QLabel("Local model"))
        self.selector = QComboBox()
        self.selector.addItem("No model selected", "")
        self.selector.addItem("Qwen3.5 · 4B · MLX 4-bit", PRESET)
        layout.addWidget(self.selector)
        choose = QPushButton("Choose local MLX folder…")
        self.choose = choose
        choose.clicked.connect(self.choose_local)
        layout.addWidget(choose)
        self.choose_gguf = QPushButton('Choose GGUF file…')
        self.choose_gguf.clicked.connect(self.choose_gguf_file)
        layout.addWidget(self.choose_gguf)
        self.download_button = QPushButton("Download preset (~3.1 GB)")
        self.download_button.clicked.connect(self.download_preset)
        layout.addWidget(self.download_button)
        self.cancel_button = QPushButton("Cancel download")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(lambda: self.task.requestInterruption())
        layout.addWidget(self.cancel_button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        note = QLabel("Models are saved to disk. Emails and answers stay in RAM. Models unload after each answer.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.memory = QLabel('Model unloaded. Memory is measured during inference.')
        self.memory.setWordWrap(True)
        self.memory.setToolTip('Worker peak RAM includes model, tokenizer, caches, and runtime. MLX active/peak values are allocator measurements, not additional RAM to sum. Dedicated GPU VRAM is not measured.')
        layout.addWidget(self.memory)
        self.parameter_file = self.model_folder.parent.parent / 'inference-settings.json'
        advanced = QPushButton('Inference parameters ▸')
        advanced.setCheckable(True)
        layout.addWidget(advanced)
        self.parameter_scroll = QScrollArea()
        self.parameter_scroll.setWidgetResizable(True)
        self.parameter_scroll.setMaximumHeight(340)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(4, 4, 4, 4)
        self.controls = {}
        for key, (label, kind, lower, upper) in inference_settings.FIELDS.items():
            control = QSpinBox() if kind is int else QDoubleSpinBox()
            control.setRange(lower, upper)
            if kind is float:
                control.setSingleStep(0.05)
            control.valueChanged.connect(lambda _value: self.parameters_changed.emit())
            self.controls[key] = control
            form.addRow(label, control)
        save = QPushButton('Save model profile')
        save.clicked.connect(self.save_parameters)
        form.addRow(save)
        reload = QPushButton('Reload JSON')
        reload.clicked.connect(self.load_parameters)
        form.addRow(reload)
        self.parameter_status = QLabel()
        self.parameter_status.setWordWrap(True)
        self.parameter_status.setTextFormat(Qt.TextFormat.PlainText)
        self.parameter_status.setToolTip(str(self.parameter_file))
        form.addRow(self.parameter_status)
        self.parameter_scroll.setWidget(form_widget)
        self.parameter_scroll.hide()
        advanced.toggled.connect(self.parameter_scroll.setVisible)
        layout.addWidget(self.parameter_scroll)
        layout.addStretch()

        selected = self.settings.value("model/selection", "", type=str)
        if selected and selected != PRESET:
            self.selector.addItem("Local: " + Path(selected).name, selected)
        self.selector.setCurrentIndex(max(0, self.selector.findData(selected)))
        self.selector.currentIndexChanged.connect(self.save_selection)
        self.update_status()
        self.load_parameters()

    def choose_local(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose local MLX model folder")
        if not folder:
            return
        self.select_local(folder)

    def choose_gguf_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose GGUF model', '', 'GGUF models (*.gguf)')
        if path:
            self.select_local(path)

    def select_local(self, path):
        # Keep just one custom folder in the small selector.
        if self.selector.count() > 2:
            self.selector.removeItem(2)
        self.selector.addItem("Local: " + Path(path).name, path)
        self.selector.setCurrentIndex(2)

    def save_selection(self):
        self.settings.setValue("model/selection", self.selector.currentData())
        self.update_status()
        self.load_parameters()

    def load_parameters(self):
        try:
            values = inference_settings.parameters(self.parameter_file, self.selector.currentData())
            for key, control in self.controls.items():
                control.blockSignals(True)
                control.setValue(values[key])
                control.blockSignals(False)
            self.parameter_error = False
            self.parameter_status.setText('Non-thinking mode. Profile loaded; hover here for JSON path.')
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self.parameter_error = True
            self.parameter_status.setText('Cannot load inference-settings.json. Check its format, values, and permissions, then Reload JSON.')
        self.parameters_changed.emit()

    def parameters(self):
        if self.parameter_error:
            raise ValueError(self.parameter_status.text())
        return inference_settings.validate({key: control.value() for key, control in self.controls.items()})

    def save_parameters(self):
        try:
            inference_settings.save(self.parameter_file, self.selector.currentData(), self.parameters())
            self.parameter_status.setText('Model profile saved. Hover here for JSON path.')
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self.parameter_status.setText('Could not save profile. Check JSON format and folder permissions.')

    def update_status(self):
        selected = self.selector.currentData()
        downloaded = model_download.ready(self.model_folder)
        self.download_button.setText("Preset downloaded" if downloaded else "Download preset (~3.1 GB)")
        self.download_button.setEnabled(selected == PRESET and not downloaded and self.task is None)
        if not selected:
            text = "No model selected."
        elif selected == PRESET:
            state = "Downloaded; not loaded." if downloaded else "Not downloaded completely."
            text = state + "\nMLX requires Apple Silicon."
        elif Path(selected).suffix.lower() == '.gguf' and Path(selected).is_file():
            text = 'Local GGUF selected; llama.cpp backend.'
        elif not Path(selected).is_dir():
            text = "Folder is missing. Choose another folder."
        else:
            text = "Local folder selected; model compatibility has not been checked."
        self.status.setText(text)
        self.status.setToolTip(str(self.model_folder) if selected == PRESET else selected)

    def download_preset(self):
        self.task = DownloadTask(self.model_folder, self)
        self.selector.setEnabled(False)
        self.choose.setEnabled(False)
        self.choose_gguf.setEnabled(False)
        self.download_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText("Checking preset files…")
        self.task.progress.connect(self.status.setText)
        self.task.outcome.connect(self.status.setText)
        self.task.finished.connect(self.download_finished)
        self.task.start()

    def download_finished(self):
        self.task.deleteLater()
        self.task = None
        self.selector.setEnabled(True)
        self.choose.setEnabled(True)
        self.choose_gguf.setEnabled(True)
        self.cancel_button.setEnabled(False)
        outcome = self.status.text()
        self.update_status()
        if not model_download.ready(self.model_folder):
            self.status.setText(outcome)

    def selected_folder(self):
        selected = self.selector.currentData()
        if selected == PRESET:
            return self.model_folder if model_download.ready(self.model_folder) else None
        if selected:
            path = Path(selected)
            if path.is_dir() or (path.suffix.lower() == '.gguf' and path.is_file()):
                return path
        return None
