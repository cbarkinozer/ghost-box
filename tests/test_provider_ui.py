"""Provider switching clears RAM and Outlook never dispatches through Gmail."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QMessageBox
from ghost_box.ui.window import prepare_qt_plugins
from ghost_box.ui.compose import ComposeDialog
from test_mail_controls import window_fixture,mail


class ProviderUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_qt_plugins();cls.app=QApplication.instance() or QApplication([])

    def drain(self,owner):
        if owner.task is not None:owner.task.wait()
        for _ in range(15):self.app.processEvents()

    def test_switch_fetch_and_reviewed_send_use_selected_provider_only(self):
        with window_fixture(self.app) as (owner,directory):
            source=mail('one','Budget','PRIVATE old Gmail mail') | dict(message_id='<parent@example.com>',thread_id='thread',cc='')
            owner.mailbox.replace(owner.email,[source]);owner.refresh_messages();owner.select_visible()
            with (patch.object(owner,'model_configuration',return_value=(Path('/synthetic'),owner.caspy.parameters())),
                  patch.object(owner.runtime,'load')):
                owner.question.setPlainText('Summarize');owner.ask_selected()
            owner.inference_event(dict(kind='text',text='PRIVATE old Gmail answer'))
            owner.inference_event(dict(kind='done',status='success'))
            self.assertTrue(owner.history.sessions)
            with (patch('ghost_box.mail.outlook.saved_account',return_value='me@example.com'),
                  patch('ghost_box.mail.gmail.disconnect') as disconnect):
                owner.provider_picker.setCurrentIndex(owner.provider_picker.findData('outlook'));self.drain(owner)
                disconnect.assert_not_called()
            self.assertEqual(owner.email,'me@example.com')
            self.assertEqual(owner.provider.NAME,'Outlook')
            self.assertFalse(owner.history.sessions);self.assertFalse(owner.mailbox.accounts)
            self.assertEqual(owner.answer_markdown,'');self.assertFalse(owner.answer.sources)
            self.assertTrue(owner.skip_promotions.isHidden())
            self.assertIn('Outlook',owner.connect_button.text())
            with (patch('ghost_box.mail.outlook.fetch',return_value=dict(count=0,cancelled=False)) as fetch,
                  patch('ghost_box.mail.gmail.fetch') as gmail_fetch):
                owner.fetch_mail();self.drain(owner)
                fetch.assert_called_once();gmail_fetch.assert_not_called()
                self.assertFalse(fetch.call_args.kwargs['exclude_promotions'])
            with (patch('ghost_box.mail.outlook.can_send',return_value=True),
                  patch('ghost_box.mail.outlook.send',return_value='accepted') as send,
                  patch('ghost_box.mail.gmail.send') as gmail_send):
                source=source | {'body':'Outlook original message'}
                dialog=ComposeDialog(source,owner.email,'reply',owner);self.drain(dialog)
                dialog.body.setPlainText('Approved reply text.')
                with patch.object(QMessageBox,'exec',return_value=QMessageBox.StandardButton.Cancel):dialog.review_send()
                send.assert_not_called()
                with patch.object(QMessageBox,'exec',return_value=QMessageBox.StandardButton.Yes):dialog.review_send()
                self.drain(dialog)
                send.assert_called_once();gmail_send.assert_not_called()
                self.assertIn('mime',send.call_args.args[1]);self.assertTrue(dialog.locked)
                self.assertIn('Outlook',dialog.status.text());dialog.reject()
