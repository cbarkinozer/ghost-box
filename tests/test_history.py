"""Native session navigation preserves answers and source snapshots only in RAM."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from ghost_box.ui.window import Window, prepare_qt_plugins


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_qt_plugins()
        cls.app = QApplication.instance() or QApplication([])

    def test_sessions_messages_branching_fetch_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=QSettings(str(Path(directory)/'settings.ini'),QSettings.Format.IniFormat)
            with (patch('ghost_box.ui.caspy.QSettings', return_value=settings),
                  patch('ghost_box.ui.window.QSettings', return_value=settings),
                  patch('ghost_box.ui.window.QStandardPaths.writableLocation', return_value=directory),
                  patch('ghost_box.mail.gmail.saved_account',return_value='')):
                window=Window();window.task.wait()
                for _ in range(10):self.app.processEvents()
                window.show_account('me@example.com')
                source=dict(id='one',subject='Budget',timestamp=1,sender='Ada',recipients='me@example.com',body='PRIVATE ORIGINAL BODY')
                window.mailbox.replace(window.email,[source]);window.refresh_messages();window.mail_list.selectAll()
                with (patch.object(window,'model_configuration',return_value=(Path(directory),window.caspy.parameters())),
                      patch.object(window.runtime,'load') as send):
                    window.ask_selected(summarize=True)
                    window.inference_event(dict(kind='diagnostic',stage='extraction',code='quote_mismatch',
                                                call=1,sources=[1],text='PRIVATE RAW DIAGNOSTIC INPUT'))
                    self.assertEqual(len(window.diagnostic_rows),1)
                    self.assertNotIn('PRIVATE',str(window.diagnostic_rows))
                    window.inference_event(dict(kind='step',step_id=1,action='summary_extract',sources=[1],state='done'))
                    window.inference_event(dict(kind='search',text='BM25 kullanılmadı · Seçili mailler doğrudan inceleniyor.'))
                    cards=[dict(id='one',source=1,kind='action_requested',facts=[dict(id='1.1',text='Approval requested.',quote='PRIVATE ORIGINAL BODY')])]
                    window.inference_event(dict(kind='summary',cards=cards,markdown='Summary approval requested. [1]',complete=True))
                    window.inference_event(dict(kind='done',status='success'))
                    self.assertEqual(len(window.history.sessions),1)
                    window.question.setPlainText('What does that mean?')
                    window.ask_selected(follow_up=True)
                    request=send.call_args.kwargs['request']
                    self.assertEqual(window.diagnostic_rows,[])
                    self.assertEqual(window.work_steps.rows,[])
                    self.assertIn('Approval requested',request['previous']['answer'])
                    self.assertNotIn('PRIVATE ORIGINAL BODY',request['previous']['answer'])
                    self.assertTrue(request['follow_up']);self.assertFalse(request['use_search'])
                    window.inference_event(dict(kind='text',text='You need to review it. [1]'))
                    window.inference_event(dict(kind='done',status='success'))
                    self.assertEqual(len(window.history.sessions[0]['messages']),2)
                    window.question.setPlainText('Another independent question')
                    window.ask_selected()
                    self.assertFalse(send.call_args.kwargs['request']['follow_up'])
                    window.inference_event(dict(kind='text',text='Independent answer.'))
                    window.inference_event(dict(kind='done',status='success'))
                    self.assertEqual(len(window.history.sessions),2)
                    window.session_picker.setCurrentIndex(0)
                    window.message_picker.setCurrentIndex(0)
                    self.assertIn('Summary approval requested',window.answer.toPlainText())
                    self.assertEqual(window.diagnostic_rows[0]['code'],'quote_mismatch')
                    self.assertEqual(window.work_steps.rows[0]['action'],'summary_extract')
                    self.assertIn('BM25 kullanılmadı',window.search_status.text())
                    window.question.setPlainText('Branch from the summary')
                    window.ask_selected(follow_up=True)
                    self.assertIn('Approval requested',send.call_args.kwargs['request']['previous']['answer'])
                    self.assertNotIn('You need to review',send.call_args.kwargs['request']['previous']['answer'])
                    window.inference_event(dict(kind='text',text='Branched answer.'))
                    window.inference_event(dict(kind='done',status='success'))
                    self.assertEqual(len(window.history.sessions[0]['messages']),3)
                window.mailbox.replace(window.email,[]);window.refresh_messages()
                self.assertIn('Branched answer',window.answer.toPlainText())
                window.preview_source('one')
                self.assertIn('PRIVATE ORIGINAL BODY',window.reader.toPlainText())
                window.clear_history()
                self.assertFalse(window.history.sessions)
                self.assertFalse(window.answer.sources)
                self.assertEqual(window.diagnostic_rows,[])
                self.assertEqual(window.work_steps.rows,[])
                self.assertEqual(window.reader.toPlainText(),'')
                window.close()
                restored=Window();restored.task.wait()
                for _ in range(10):self.app.processEvents()
                self.assertFalse(restored.history.sessions)
                self.assertEqual(restored.answer.toPlainText(),'')
                # Numeric/model settings can be written; email/chat content cannot.
                for path in Path(directory).rglob('*'):
                    if path.is_file():
                        self.assertNotIn(b'PRIVATE ORIGINAL BODY',path.read_bytes())
                        self.assertNotIn(b'Branched answer',path.read_bytes())
                restored.close()
