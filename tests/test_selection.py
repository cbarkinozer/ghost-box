"""Selected email scope and downloaded-preset UI state, without private data."""

import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from main import Window, prepare_qt_plugins
from mail_context import SYSTEM, build_context


class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_qt_plugins()
        cls.app = QApplication.instance() or QApplication([])

    def test_selection_counts_all_and_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / 'settings.ini'), QSettings.Format.IniFormat)
            with (patch('caspy.QSettings', return_value=settings),
                  patch('main.QStandardPaths.writableLocation', return_value=directory),
                  patch('gmail.saved_account', return_value='')):
                window = Window()
                window.task.wait()
                for _ in range(10):
                    self.app.processEvents()
                window.show_account('synthetic@example.com')
                window.mailbox.replace(window.email, [
                    {'id': name, 'timestamp': index, 'sender': 'Test', 'recipients': 'Test',
                     'subject': name, 'body': name + ' synthetic body'}
                    for index, name in enumerate(('selected-one', 'selected-two', 'excluded-three'))
                ])
                window.refresh_messages()
                window.question.setPlainText('What happened?')
                window.mail_list.item(1).setSelected(True)
                window.mail_list.item(2).setSelected(True)
                selected = window.selected_messages()
                self.assertEqual({m['id'] for m in selected}, {'selected-one', 'selected-two'})
                context = build_context(selected, window.question.toPlainText())
                self.assertNotIn('excluded-three', context)
                chars = len(SYSTEM) + len(context)
                self.assertIn(f'{chars:,} input characters', window.scope_label.text())
                self.assertIn(f'~{math.ceil(chars / 4):,} tokens', window.scope_label.text())
                self.assertTrue(window.ask_button.isEnabled())
                window.mail_list.selectAll()
                self.assertEqual(len(window.selected_messages()), 3)
                window.answer.setPlainText('Old answer')
                window.mail_list.clearSelection()
                self.assertFalse(window.ask_button.isEnabled())
                self.assertEqual(window.answer.toPlainText(), '')
                self.assertEqual(window.selected_messages(), [])
                with patch('model_download.ready', return_value=True):
                    window.caspy.selector.setCurrentIndex(1)
                    self.assertEqual(window.caspy.download_button.text(), 'Preset downloaded')
                    self.assertFalse(window.caspy.download_button.isEnabled())
                    window.mail_list.selectAll()
                    with patch('main.find_spec', return_value=None):
                        window.ask_button.click()
                    self.assertIn('runtime is missing', window.inference_status.text())
                    self.assertIn('--extra inference', window.inference_status.text())
                    self.assertIsNone(window.inference)
                window.question.setPlainText('Use Turkish and highlight deadlines.')
                with patch('main.find_spec', return_value=None):
                    window.summary_button.click()
                self.assertIn('Summarize the selected emails', window.question_text())
                self.assertIn('Use Turkish and highlight deadlines.', window.question_text())
                self.assertNotIn('Use Turkish', window.caspy.parameter_file.read_text())
                window.question.clear()
                self.assertTrue(window.summary_button.isEnabled())
                self.assertFalse(window.ask_button.isEnabled())
                with patch('main.find_spec', return_value=None):
                    window.summary_button.click()
                self.assertIn('Summarize the selected emails', window.question_text())

                gguf = Path(directory) / 'synthetic.gguf'
                gguf.write_bytes(b'GGUF')
                window.caspy.select_local(str(gguf))
                self.assertEqual(window.caspy.selected_folder(), gguf)
                window.caspy.controls['temperature'].setValue(0.25)
                window.caspy.save_parameters()
                window.caspy.selector.setCurrentIndex(1)
                self.assertEqual(window.caspy.parameters()['temperature'], 0.7)
                window.caspy.selector.setCurrentIndex(2)
                self.assertEqual(window.caspy.parameters()['temperature'], 0.25)
                window.close()
