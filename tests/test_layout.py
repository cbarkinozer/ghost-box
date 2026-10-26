"""Answer/steps share a usable area; optional panels release space without global scrolling."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QPushButton
from ghost_box.ui.window import Window, prepare_qt_plugins
from test_mail_controls import window_fixture


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
                window.show_diagnostics()
                dialog=window.diagnostics_dialog
                self.assertIsNotNone(dialog)
                window.show_diagnostics()
                self.assertIs(window.diagnostics_dialog,dialog)
                dialog.reject()
                self.assertIsNone(window.diagnostics_dialog)
                window.close()

    def test_caspy_fits_sidebar_with_parameters_and_long_model_name(self):
        with window_fixture(self.app) as (window, _):
            window.show()
            panel = window.caspy
            panel.selector.addItem('Local: ' + 'long-model-name-' * 20, '')
            panel.selector.setCurrentIndex(panel.selector.count() - 1)
            advanced = next(button for button in panel.findChildren(QPushButton)
                            if button.text().startswith('Inference parameters'))
            advanced.setChecked(True)
            scroll = next(area for area in window.findChildren(QScrollArea)
                          if area.widget() is panel)
            for width in (260, 340, 260):
                window.centralWidget().setSizes([280, 640, width])
                for _ in range(5):
                    self.app.processEvents()
                for area in (scroll, panel.parameter_scroll):
                    self.assertEqual(area.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                    self.assertEqual(area.horizontalScrollBar().maximum(), 0)
                    self.assertLessEqual(area.widget().width(), area.viewport().width())
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
            self.app.processEvents()
            self.assertGreater(scroll.verticalScrollBar().value(), 0)
            self.assertTrue(panel.test_output.isVisible())
