"""Selected email scope and downloaded-preset UI state, without private data."""

import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QSettings, QUrl
from PySide6.QtWidgets import QApplication

from ghost_box.ui.window import Window, prepare_qt_plugins
from ghost_box.mail.context import SYSTEM, build_context


class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_qt_plugins()
        cls.app = QApplication.instance() or QApplication([])

    def test_selection_counts_all_and_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / 'settings.ini'), QSettings.Format.IniFormat)
            with (patch('ghost_box.ui.caspy.QSettings', return_value=settings),
                  patch('ghost_box.ui.window.QSettings', return_value=settings),
                  patch('ghost_box.ui.window.QStandardPaths.writableLocation', return_value=directory),
                  patch('ghost_box.mail.gmail.saved_account', return_value='')):
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
                context = build_context(selected, window.question_text())
                self.assertIn('Default response language: Turkish', window.question_text())
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
                self.assertEqual(window.answer.toPlainText(), 'Old answer')
                self.assertEqual(window.selected_messages(), [])
                window.answer.sources = {message['id']: message for message in selected}
                window.answer.render('## Decision\n\n**Confirmed** [selected-one, selected-two]')
                rendered = window.answer.toPlainText()
                self.assertIn('Source 1', rendered)
                window.mail_list.item(0).setSelected(True)
                before = {message['id'] for message in window.selected_messages()}
                window.answer.open_source(QUrl('ghostmail:selected-one'))
                self.assertIn('selected-one synthetic body', window.reader.toPlainText())
                self.assertEqual(before, {message['id'] for message in window.selected_messages()})
                self.assertEqual(window.answer.toPlainText(), rendered)
                current = window.mail_list.currentItem()
                window.answer.open_source(QUrl('ghostmail:excluded-three'))
                self.assertIs(window.mail_list.currentItem(), current)
                window.language.setCurrentIndex(1)
                self.assertEqual(settings.value('response_language'), 'English')
                self.assertIn('Default response language: English', window.question_text())
                self.assertEqual(window.answer.toPlainText(), rendered)
                with patch('ghost_box.models.download.ready', return_value=True):
                    window.caspy.selector.setCurrentIndex(1)
                    self.assertEqual(window.caspy.download_button.text(), 'Preset downloaded')
                    self.assertFalse(window.caspy.download_button.isEnabled())
                    window.mail_list.selectAll()
                    with patch('ghost_box.ui.window.find_spec', return_value=None):
                        window.ask_button.click()
                    self.assertIn('runtime is missing', window.inference_status.text())
                    self.assertIn('--extra inference', window.inference_status.text())
                    self.assertIsNone(window.runtime.process)
                window.question.setPlainText('Use Turkish and highlight deadlines.')
                with patch('ghost_box.ui.window.find_spec', return_value=None):
                    window.summary_button.click()
                self.assertIn('Summarize the selected emails', window.question_text())
                self.assertIn('Use Turkish and highlight deadlines.', window.question_text())
                self.assertNotIn('Use Turkish', window.caspy.parameter_file.read_text())
                window.question.clear()
                self.assertTrue(window.summary_button.isEnabled())
                self.assertFalse(window.ask_button.isEnabled())
                with patch('ghost_box.ui.window.find_spec', return_value=None):
                    window.summary_button.click()
                self.assertIn('Summarize the selected emails', window.question_text())

                window.answer_markdown = 'Previous summary [1]'
                window.answer_question = 'Summarize the selected emails'
                window.answer.render(window.answer_markdown)
                window.update_scope()
                self.assertTrue(window.followup_button.isEnabled())
                window.followup_button.click()
                self.assertIn('Type your follow-up', window.inference_status.text())
                self.assertEqual(window.answer.toPlainText(), 'Previous summary Source 1')
                self.assertIsNone(window.runtime.process)
                window.question.setPlainText('Explain that summary.')
                with (patch.object(window, 'model_configuration', return_value=(Path(directory), window.caspy.parameters())),
                      patch.object(window.runtime, 'load') as send):
                    window.followup_button.click()
                request = send.call_args.kwargs['request']
                self.assertIn('Previous summary [1]', request['question'])
                self.assertEqual({mail['id'] for mail in request['emails']}, {'selected-one', 'selected-two'})
                window.inference_event({'kind': 'text', 'text': 'Explanation [1]'})
                window.inference_event({'kind': 'progress', 'text': 'Complete', 'completed': 1, 'total': 1})
                window.inference_event({'kind': 'done', 'status': 'success'})
                self.assertFalse(window.answer_running)

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
                self.assertFalse(window.answer.sources)
                restored = Window()
                restored.task.wait()
                for _ in range(10):
                    self.app.processEvents()
                self.assertEqual(restored.language.currentData(), 'English')
                restored.close()
