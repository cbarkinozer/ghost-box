"""Worker reuse, reload, idle unloading, and cancellation without a real model."""

import os
from pathlib import Path
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from ghost_box.models.session import ModelSession
from ghost_box.ui.window import prepare_qt_plugins


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_qt_plugins()
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, predicate, timeout=2000):
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(2)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        end = QTimer()
        end.setSingleShot(True)
        end.timeout.connect(loop.quit)
        poll.start(); end.start(timeout)
        if not predicate():
            loop.exec()
        self.assertTrue(predicate(), 'Worker condition timed out')

    def session(self, idle_ms=300000):
        session = ModelSession(idle_ms=idle_ms)
        session.worker_arguments = ['-u', str(Path(__file__).parent / 'fixtures' / 'model_worker.py')]
        self.addCleanup(session.shutdown)
        return session

    def test_reuse_idle_timeout_and_busy_protection(self):
        session = self.session(idle_ms=60)
        events = []
        session.event.connect(events.append)
        session.load(Path('/synthetic/model'), {'tokens': 10})
        self.wait_for(lambda: session.state == 'ready')
        pid = session.process.processId()
        for _ in range(2):
            session.load(Path('/synthetic/model'), {'tokens': 10}, {'question': 'Synthetic'})
            self.assertEqual(session.state, 'generating')
            self.assertFalse(session.idle_timer.isActive())
            self.wait_for(lambda: not session.busy)
            self.assertEqual(session.process.processId(), pid)
        self.assertEqual(sum(event['kind'] == 'done' for event in events), 2)
        self.wait_for(lambda: session.process is None)
        self.assertEqual(session.state, 'unloaded')

    def test_reload_cancel_and_recover(self):
        session = self.session()
        events = []
        session.event.connect(events.append)
        session.load(Path('/synthetic/model'), {'tokens': 10})
        self.wait_for(lambda: session.state == 'ready')
        pid = session.process.processId()
        session.load(Path('/synthetic/model'), {'tokens': 20}, {'question': 'Synthetic'})
        self.wait_for(lambda: session.state == 'generating')
        self.assertNotEqual(session.process.processId(), pid)
        session.unload('Stopped by user')
        self.wait_for(lambda: session.process is None)
        self.assertTrue(any(event.get('status') == 'stopped' for event in events))
        session.load(Path('/synthetic/another'), {'tokens': 20})
        self.wait_for(lambda: session.state == 'ready')
        session.unload()
        self.wait_for(lambda: session.process is None)
