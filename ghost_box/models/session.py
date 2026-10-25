"""One warm worker, explicit load/unload, and a five-minute idle timeout."""

import json
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class ModelSession(QObject):
    event = Signal(dict)
    state_changed = Signal(str)

    def __init__(self, parent=None, idle_ms=300_000):
        super().__init__(parent)
        self.process = None
        self.state = 'unloaded'
        self.folder = None
        self.parameters = None
        self.pending_request = None
        self.pending_start = None
        self.buffer = b''
        self.reason = ''
        self.closing = False
        self.active_request = False
        self.error_reported = False
        self.worker_arguments = ['-u', '-m', 'ghost_box.models.worker']
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.setInterval(idle_ms)
        self.idle_timer.timeout.connect(lambda: self.unload('Five minutes idle'))

    @property
    def busy(self):
        return self.active_request

    def set_state(self, state):
        self.state = state
        self.state_changed.emit(state)

    def matches(self, folder, parameters):
        return self.folder == folder and self.parameters == parameters

    def load(self, folder, parameters, request=None):
        if self.busy:
            return
        if self.process is not None:
            if self.matches(folder, parameters) and self.state in ('loading', 'ready'):
                if request is not None:
                    self.active_request = True
                    self.pending_request = request
                    if self.state == 'ready':
                        self.send_request()
                elif self.state == 'ready':
                    self.idle_timer.start()
                return
            self.pending_start = (folder, parameters.copy(), request)
            self.stop_process('Reloading selected model/settings')
            return
        self.start_process(folder, parameters, request)

    def start_process(self, folder, parameters, request):
        self.folder, self.parameters = folder, parameters.copy()
        self.pending_request = request
        self.active_request = request is not None
        self.buffer = b''
        self.reason = ''
        self.error_reported = False
        process = QProcess(self)
        self.process = process
        process.setProgram(sys.executable)
        process.setArguments(self.worker_arguments)
        process.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
        process.started.connect(lambda: self.write({'action': 'load', 'folder': str(folder), 'parameters': parameters}))
        process.readyReadStandardOutput.connect(self.read_events)
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.finished.connect(self.finished)
        process.errorOccurred.connect(self.process_error)
        self.set_state('loading')
        process.start()

    def write(self, command):
        self.process.write(json.dumps(command).encode() + b'\n')

    def send_request(self):
        request, self.pending_request = self.pending_request, None
        self.idle_timer.stop()
        self.set_state('generating')
        self.write({'action': 'run', **request})

    def read_events(self):
        if self.process is None:
            return
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict) or not isinstance(event.get('kind'), str):
                continue
            if self.state == 'unloading':
                continue
            if event.get('kind') == 'error':
                self.error_reported = True
            if event.get('kind') == 'ready':
                self.set_state('ready')
                if self.pending_request is not None:
                    self.send_request()
                else:
                    self.idle_timer.start()
            elif event.get('kind') == 'done':
                self.active_request = False
                self.set_state('ready')
                self.idle_timer.start()
            self.event.emit(event)

    def unload(self, reason='Manually unloaded'):
        self.pending_start = None
        self.stop_process(reason)

    def stop_process(self, reason):
        self.idle_timer.stop()
        self.reason = reason
        if self.process is not None:
            self.set_state('unloading')
            self.process.kill()
        else:
            self.pending_request = None
            self.set_state('unloaded')

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.error_reported = True
            self.event.emit({'kind': 'error', 'text': 'Could not start the local model worker.'})
            self.finished(1)

    def finished(self, exit_code, *_):
        if self.process is None:
            return
        was_running = self.active_request
        # state may already be unloading; a pending answer also needs a terminal event.
        self.read_events()
        self.process.deleteLater()
        self.process = None
        self.pending_request = None
        self.active_request = False
        self.buffer = b''
        self.folder = None
        self.parameters = None
        reason = self.reason
        self.set_state('unloaded')
        if was_running:
            self.event.emit({'kind': 'done', 'status': 'stopped' if reason else 'error', 'text': reason})
        elif exit_code and not reason and not self.error_reported:
            self.event.emit({'kind': 'error', 'text': 'Model worker exited unexpectedly. Check runtime and model compatibility.'})
            self.event.emit({'kind': 'done', 'status': 'error'})
        pending, self.pending_start = self.pending_start, None
        if pending is not None and not self.closing:
            self.start_process(*pending)

    def shutdown(self):
        self.closing = True
        self.unload('Application closing')
        if self.process is not None:
            self.process.waitForFinished(3000)
