"""Small model-selection panel and on-demand preset download."""

from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QLabel, QPushButton, QVBoxLayout, QWidget,
    QDoubleSpinBox, QSpinBox, QFormLayout, QScrollArea, QHBoxLayout, QPlainTextEdit,
    QSizePolicy,
)

from ..models import download as model_download
from ..models import settings as inference_settings
from ..models.download import PRESET, GGUF_PRESET
from ..models.projection import describe
from .answer_view import AnswerView


class DownloadTask(QThread):
    progress = Signal(str)
    outcome = Signal(str)

    def __init__(self, folder, parent, manifest=None, removing=False):
        super().__init__(parent)
        self.folder = folder
        self.manifest = manifest
        self.removing = removing

    def run(self):
        if self.removing:
            try:
                model_download.remove_preset(self.folder.parent, self.manifest['repo'])
                self.outcome.emit('Downloaded preset removed. You can download it again.')
            except ValueError as error:
                self.outcome.emit(str(error))
            except OSError:
                self.outcome.emit('Could not finish removing the preset. Check model-folder permissions and retry.')
            return
        try:
            model_download.download(self.folder, self.progress.emit, self.isInterruptionRequested, self.manifest)
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
    remove_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("Ghost-box", "Ghost-box")
        self.task = None
        self.model_folder = Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )) / "models" / model_download.REVISION
        self.gguf_folder = self.model_folder.parent / model_download.GGUF_MANIFEST["revision"]
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>👻 Caspy</b>"))
        layout.addWidget(QLabel("Local model"))
        self.selector = QComboBox()
        self.selector.setMinimumContentsLength(12)
        self.selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.selector.addItem("No model selected", "")
        self.selector.addItem("Qwen3.5 · 4B · MLX 4-bit", PRESET)
        self.selector.addItem("Qwen3.5 · 4B · GGUF Q4_K_M", GGUF_PRESET)
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
        self.remove_button = QPushButton('Remove preset…')
        self.remove_button.setToolTip('Removes only application-managed preset files. Custom model folders and files are never removed.')
        self.remove_button.clicked.connect(self.remove_requested.emit)
        layout.addWidget(self.remove_button)
        self.cancel_button = QPushButton("Cancel download")
        self.cancel_button.setEnabled(False)
        self.cancel_button.hide()
        self.cancel_button.clicked.connect(lambda: self.task.requestInterruption())
        layout.addWidget(self.cancel_button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        note = QLabel("Emails and answers stay in RAM.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.model_state = QLabel('Model: unloaded')
        layout.addWidget(self.model_state)
        self.model_state.setWordWrap(True)
        self.model_state.setTextFormat(Qt.TextFormat.PlainText)
        lifecycle = QHBoxLayout()
        self.load_button = QPushButton('Load')
        self.unload_button = QPushButton('Unload')
        self.unload_button.setEnabled(False)
        lifecycle.addWidget(self.load_button)
        lifecycle.addWidget(self.unload_button)
        layout.addLayout(lifecycle)
        self.memory = QLabel('Memory is measured during inference.')
        self.memory.setWordWrap(True)
        self.memory.setToolTip('Worker peak RAM includes model, tokenizer, caches, and runtime. MLX active/peak values are allocator measurements, not additional RAM to sum. Dedicated GPU VRAM is not measured.')
        layout.addWidget(self.memory)
        self.parameter_file = self.model_folder.parent.parent / 'inference-settings.json'
        advanced = QPushButton('Inference parameters ▸')
        advanced.setCheckable(True)
        layout.addWidget(advanced)
        self.parameter_scroll = QScrollArea()
        self.parameter_scroll.setWidgetResizable(True)
        self.parameter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.parameter_scroll.setMaximumHeight(340)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setContentsMargins(4, 4, 4, 4)
        self.controls = {}
        for key, (label, kind, lower, upper) in inference_settings.FIELDS.items():
            control = QSpinBox() if kind is int else QDoubleSpinBox()
            control.setRange(lower, upper)
            if kind is float:
                control.setSingleStep(0.05)
            control.valueChanged.connect(self.parameter_changed)
            if key == 'max_output_tokens':
                control.setToolTip('Summary/draft output ceiling. Ask emails and Follow up use at most 512 output tokens for short answers.')
            self.controls[key] = control
            form.addRow(label, control)
        self.projection = QLabel()
        self.projection.setWordWrap(True)
        form.addRow(self.projection)
        save = QPushButton('Save model profile')
        save.clicked.connect(self.save_parameters)
        form.addRow(save)
        reload = QPushButton('Reload JSON')
        reload.clicked.connect(self.load_parameters)
        form.addRow(reload)
        self.reset_button = QPushButton('Reset model defaults')
        self.reset_button.clicked.connect(self.reset_parameters)
        form.addRow(self.reset_button)
        self.parameter_status = QLabel()
        self.parameter_status.setWordWrap(True)
        self.parameter_status.setTextFormat(Qt.TextFormat.PlainText)
        self.parameter_status.setToolTip(str(self.parameter_file))
        form.addRow(self.parameter_status)
        self.parameter_scroll.setWidget(form_widget)
        self.parameter_scroll.hide()
        advanced.toggled.connect(self.parameter_scroll.setVisible)
        layout.addWidget(self.parameter_scroll)
        test_toggle = QPushButton('Try model ▾')
        test_toggle.setCheckable(True)
        test_toggle.setChecked(True)
        layout.addWidget(test_toggle)
        test_panel = QWidget()
        test_layout = QVBoxLayout(test_panel)
        test_layout.setContentsMargins(0, 0, 0, 0)
        self.test_input = QPlainTextEdit()
        self.test_input.setPlaceholderText('Test a prompt · no emails included')
        self.test_input.setFixedHeight(85)
        test_layout.addWidget(self.test_input)
        buttons = QHBoxLayout()
        self.test_run = QPushButton('Run')
        self.test_stop = QPushButton('Stop')
        self.test_stop.setEnabled(False)
        self.test_clear = QPushButton('Clear')
        for button in (self.test_run, self.test_stop, self.test_clear):
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            buttons.addWidget(button)
        test_layout.addLayout(buttons)
        self.test_status = QLabel('Single prompt · RAM only')
        self.test_status.setTextFormat(Qt.TextFormat.PlainText)
        self.test_status.setWordWrap(True)
        test_layout.addWidget(self.test_status)
        self.test_output = AnswerView()
        self.test_output.setPlaceholderText('Model response')
        self.test_output.setMinimumHeight(160)
        test_layout.addWidget(self.test_output)
        test_toggle.toggled.connect(test_panel.setVisible)
        layout.addWidget(test_panel)
        layout.addStretch()

        selected = self.settings.value("model/selection", "", type=str)
        if selected and selected not in model_download.PRESETS:
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
        if self.selector.count() > 3:
            self.selector.removeItem(3)
        self.selector.addItem("Local: " + Path(path).name, path)
        self.selector.setCurrentIndex(3)

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
        self.update_projection()

    def parameter_changed(self):
        self.update_projection()
        self.parameters_changed.emit()

    def update_projection(self):
        try:
            self.projection.setText(describe(self.selected_folder(), self.parameters()))
        except ValueError:
            self.projection.setText('Fix inference settings to show the estimate.')

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

    def reset_parameters(self):
        if not self.selector.currentData():
            return
        try:
            inference_settings.reset(self.parameter_file, self.selector.currentData())
            self.load_parameters()
            self.parameter_status.setText('Model defaults restored and saved; other profiles kept.')
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self.parameter_status.setText('Could not reset this profile. Check JSON format and permissions; other profiles were not replaced.')

    def remove_downloaded(self, preset):
        if self.task is not None or self.selector.currentData() != preset:
            return
        manifest = model_download.PRESETS.get(preset)
        if manifest is None:
            return
        self.task = DownloadTask(self.preset_folder(preset), self, manifest, removing=True)
        self.lock_files()
        self.status.setText('Removing downloaded preset…')
        self.task.outcome.connect(self.status.setText)
        self.task.finished.connect(self.download_finished)
        self.task.start()

    def lock_files(self):
        for control in (self.selector, self.choose, self.choose_gguf, self.download_button, self.remove_button):
            control.setEnabled(False)
        self.parameters_changed.emit()

    def preset_folder(self, selected):
        return self.model_folder if selected == PRESET else self.gguf_folder

    def update_status(self):
        selected = self.selector.currentData()
        manifest = model_download.PRESETS.get(selected)
        folder = self.preset_folder(selected)
        self.reset_button.setEnabled(bool(selected))
        downloaded = bool(manifest and model_download.ready(folder, manifest))
        size = sum(item['size'] for item in manifest['files']) / 10**9 if manifest else 0
        self.download_button.setText("Preset downloaded" if downloaded else
                                     f"Download preset (~{size:.1f} GB)" if manifest else "Download preset")
        self.download_button.setEnabled(bool(manifest) and not downloaded and self.task is None)
        self.remove_button.setEnabled(bool(manifest) and folder.exists() and self.task is None)
        if not selected:
            text = "No model selected."
        elif manifest:
            state = "Preset downloaded." if downloaded else "Not downloaded completely."
            text = state + ("\nMLX requires Apple Silicon." if selected == PRESET else
                            "\nGGUF uses llama.cpp · Windows/macOS.")
        elif Path(selected).suffix.lower() == '.gguf' and Path(selected).is_file():
            text = 'Local GGUF selected; llama.cpp backend.'
        elif not Path(selected).is_dir():
            text = "Folder is missing. Choose another folder."
        else:
            text = "Local folder selected; model compatibility has not been checked."
        self.status.setText(text)
        self.status.setToolTip(str(folder) if manifest else selected)

    def download_preset(self):
        selected = self.selector.currentData()
        manifest = model_download.PRESETS.get(selected)
        if manifest is None or self.task is not None:
            return
        self.task = DownloadTask(self.preset_folder(selected), self, manifest)
        self.lock_files()
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
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
        self.cancel_button.hide()
        outcome = self.status.text()
        self.update_status()
        self.update_projection()
        manifest = model_download.PRESETS.get(self.selector.currentData())
        if not manifest or not model_download.ready(self.preset_folder(self.selector.currentData()), manifest):
            self.status.setText(outcome)
        self.parameters_changed.emit()

    def selected_folder(self):
        selected = self.selector.currentData()
        manifest = model_download.PRESETS.get(selected)
        if manifest:
            folder = self.preset_folder(selected)
            if not model_download.ready(folder, manifest):
                return None
            return folder if selected == PRESET else folder / manifest['files'][0]['name']
        if selected:
            path = Path(selected)
            if path.is_dir() or (path.suffix.lower() == '.gguf' and path.is_file()):
                return path
        return None
