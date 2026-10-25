"""Inbox filters, RAM cleanup, retained source privacy, and accurate fetch scope."""

from contextlib import contextmanager
from datetime import datetime
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QSettings,Qt
from PySide6.QtWidgets import QApplication
from ghost_box.ui.window import Window,prepare_qt_plugins


def mail(identifier,subject,body='Original body',sender='Ada <ada@example.com>'):
    return dict(id=identifier,timestamp=1,subject=subject,body=body,sender=sender,recipients='me@example.com')


@contextmanager
def window_fixture(app):
    with tempfile.TemporaryDirectory() as directory:
        settings=QSettings(str(Path(directory)/'settings.ini'),QSettings.Format.IniFormat)
        with (patch('ghost_box.ui.caspy.QSettings',return_value=settings),patch('ghost_box.ui.window.QSettings',return_value=settings),
              patch('ghost_box.ui.window.QStandardPaths.writableLocation',return_value=directory),
              patch('ghost_box.mail.gmail.saved_account',return_value='')):
            window=Window();window.task.wait()
            for _ in range(10):app.processEvents()
            window.show_account('me@example.com')
            try:yield window,Path(directory)
            finally:window.close()


class MailControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_qt_plugins();cls.app=QApplication.instance() or QApplication([])

    def answer(self,window,message,text):
        with (patch.object(window,'model_configuration',return_value=(Path('/synthetic'),window.caspy.parameters())),
              patch.object(window.runtime,'load')):
            window.mail_list.clearSelection()
            for row in range(window.mail_list.count()):
                item=window.mail_list.item(row)
                item.setSelected(item.data(Qt.ItemDataRole.UserRole)==message['id'])
            window.question.setPlainText('Question '+message['id']);window.ask_selected()
            window.inference_event(dict(kind='text',text=text))
            window.inference_event(dict(kind='done',status='success'))

    def test_filters_and_select_all_never_include_hidden_mail(self):
        with window_fixture(self.app) as (window,directory):
            window.mailbox.replace(window.email,[mail('one','Invoice','PRIVATE invoice details'),mail('two','Meeting','Discuss budget','BARKIN')])
            window.refresh_messages();window.select_visible()
            window.mail_search.setText('invoice')
            self.assertEqual([m['id'] for m in window.selected_messages()],['one'])
            window.select_visible()
            self.assertIn('1/2 emails shown',window.coverage_label.text())
            window.search_field.setCurrentIndex(window.search_field.findData('sender'))
            window.mail_search.setText('barkın')
            self.assertEqual(window.selected_messages(),[])
            window.select_visible()
            self.assertEqual([m['id'] for m in window.selected_messages()],['two'])
            self.assertIsNone(window.runtime.process)
            window.mail_search.clear();self.assertIn('2/2',window.coverage_label.text())

    def test_delete_purges_dependent_history_and_ignores_late_inference(self):
        with window_fixture(self.app) as (window,directory):
            one,two=mail('one','PRIVATE subject','PRIVATE deleted body'),mail('two','Retained mail')
            window.mailbox.replace(window.email,[one,two]);window.refresh_messages()
            self.answer(window,one,'PRIVATE old summary')
            self.answer(window,two,'Unrelated answer')
            window.select_session(0)
            window.question.setPlainText('Follow up')
            with (patch.object(window,'model_configuration',return_value=(Path('/synthetic'),window.caspy.parameters())),
                  patch.object(window.runtime,'load')):window.ask_selected(follow_up=True)
            window.mail_list.clearSelection()
            for row in range(window.mail_list.count()):
                item=window.mail_list.item(row)
                item.setSelected(item.data(Qt.ItemDataRole.UserRole)=='one')
            with patch.object(window.runtime,'unload') as unload:window.delete_selected_mail()
            unload.assert_called_once_with('Source mail removed')
            self.assertFalse(window.answer_running)
            self.assertEqual(len(window.history.sessions),1)
            self.assertEqual(window.answer_markdown,'Unrelated answer')
            self.assertEqual([m['id'] for m in window.selected_messages()],[])
            self.assertNotIn('one',window.mailbox.accounts[window.email])
            for event in (dict(kind='text',text='PRIVATE late output'),dict(kind='done',status='success'),
                          dict(kind='summary',cards=[],markdown='PRIVATE late summary')):
                window.inference_event(event)
            self.assertEqual(window.answer_markdown,'Unrelated answer')
            self.assertNotIn('PRIVATE',str(window.history.sessions))
            for path in directory.rglob('*'):
                if path.is_file():self.assertNotIn(b'PRIVATE',path.read_bytes())

    def test_clear_all_includes_retained_snapshots_and_keeps_account_and_settings(self):
        with window_fixture(self.app) as (window,directory):
            source=mail('one','Invoice','PRIVATE body')
            window.mailbox.replace(window.email,[source]);window.refresh_messages()
            self.answer(window,source,'PRIVATE summary')
            window.mailbox.replace(window.email,[]);window.refresh_messages()
            self.assertTrue(window.history.sessions)
            window.mail_search.setText('PRIVATE query');window.question.setPlainText('PRIVATE question')
            window.clear_all_mail()
            self.assertEqual(window.email,'me@example.com')
            self.assertFalse(window.mailbox.accounts);self.assertFalse(window.mailbox.coverage)
            self.assertFalse(window.history.sessions);self.assertFalse(window.answer.sources)
            self.assertEqual(window.answer_markdown,'');self.assertEqual(window.question.toPlainText(),'')
            self.assertEqual(window.mail_search.text(),'');self.assertEqual(window.reader.toPlainText(),'')
            self.assertTrue(window.caspy.parameter_file.exists())

    def test_coverage_does_not_follow_edited_controls_or_disappear_on_failed_fetch(self):
        with window_fixture(self.app) as (window,directory):
            coverage=dict(first=datetime(2026,10,24,9),last=datetime(2026,10,24,10),
                          completed_at=datetime(2026,10,24,10,5),exclude_promotions=True,count=1)
            source=mail('one','Invoice')
            window.mailbox.replace(window.email,[source],coverage);window.refresh_messages()
            original=window.coverage_description()
            window.skip_promotions.setChecked(False)
            window.fetched(dict(cancelled=True,count=0))
            self.assertEqual(window.coverage_description(),original)
            self.assertIn('cancelled',window.coverage_label.text())
            window.fetch_state='fetching'
            with patch('ghost_box.ui.window.QMessageBox.warning'):window.show_error('Fetch failed')
            self.assertIn('failed',window.coverage_label.text())
            self.assertEqual(window.coverage_description(),original)
            self.answer(window,source,'Summary')
            window.mailbox.replace(window.email,[],coverage | {'first':datetime(2026,10,25),'count':0})
            window.refresh_messages()
            self.assertEqual(window.answer_coverage,original)
            self.assertIn('2026-10-24',window.answer_scope.toolTip())
