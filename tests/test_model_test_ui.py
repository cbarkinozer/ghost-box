"""The sidebar playground reuses the worker without changing email history."""

import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from ghost_box.ui.window import prepare_qt_plugins
from test_mail_controls import window_fixture


class ModelTestUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_qt_plugins()
        cls.app = QApplication.instance() or QApplication([])

    def test_prompt_stream_stop_and_clear_are_separate_from_mail(self):
        with window_fixture(self.app) as (owner, directory):
            owner.answer_markdown = 'Existing email answer'
            owner.caspy.test_input.setPlainText('A synthetic prompt')
            with (patch.object(owner, 'model_configuration', return_value=(Path('/synthetic'), owner.caspy.parameters())),
                  patch.object(owner.runtime, 'load') as load):
                owner.test_model()
                request = load.call_args.kwargs['request']
                self.assertTrue(request['test_model'])
                self.assertNotIn('emails', request)
                self.assertFalse(owner.caspy.test_clear.isEnabled())
            owner.inference_event(dict(kind='text', text='**Test answer**'))
            owner.inference_event(dict(kind='done', status='success'))
            self.assertEqual(owner.caspy.test_output.toPlainText(), 'Test answer')
            self.assertEqual(owner.answer_markdown, 'Existing email answer')
            self.assertFalse(owner.history.sessions)
            self.assertIn('Complete', owner.caspy.test_status.text())
            self.assertFalse(owner.test_running)
            owner.clear_model_test()
            self.assertEqual(owner.caspy.test_input.toPlainText(), '')
            self.assertEqual(owner.caspy.test_output.toPlainText(), '')
