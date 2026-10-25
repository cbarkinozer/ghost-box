"""Answer/steps share a usable area; optional panels release space without global scrolling."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from ghost_box.ui.window import Window, prepare_qt_plugins


class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_qt_plugins()
        cls.app=QApplication.instance() or QApplication([])

    def test_tabs_and_optional_panels_give_space_to_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=QSettings(str(Path(directory)/'settings.ini'),QSettings.Format.IniFormat)
            with (patch('ghost_box.ui.caspy.QSettings',return_value=settings),
                  patch('ghost_box.ui.window.QSettings',return_value=settings),
                  patch('ghost_box.ui.window.QStandardPaths.writableLocation',return_value=directory),
                  patch('ghost_box.mail.gmail.saved_account',return_value='')):
                window=Window();window.task.wait()
                for _ in range(10):self.app.processEvents()
                window.show()
                self.app.processEvents()
                window.preview_toggle.setChecked(True)
                self.app.processEvents()
                with_preview=window.answer.height()
                window.preview_toggle.setChecked(False)
                self.app.processEvents()
                self.assertGreater(window.answer.height(),with_preview)
                window.output_tabs.setCurrentIndex(1)
                self.app.processEvents()
                self.assertGreater(window.work_steps.list.height(),180)
                with_model=window.work_steps.list.width()
                window.model_toggle.setChecked(False)
                self.app.processEvents()
                self.assertGreater(window.work_steps.list.width(),with_model)
                self.assertGreater(window.question.y(),window.output_tabs.geometry().bottom())
                window.close()
