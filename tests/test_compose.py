"""No sending on draft generation or cancelled approval; approved snapshot is frozen."""

import base64
from email import policy
from email.parser import BytesParser
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication,QMessageBox
from ghost_box.ui.window import Window,prepare_qt_plugins
from ghost_box.ui.compose import ComposeDialog


class ComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_qt_plugins();cls.app=QApplication.instance() or QApplication([])

    def drain(self, dialog):
        if dialog.task is not None:dialog.task.wait()
        for _ in range(15):self.app.processEvents()

    def test_cancel_and_approved_send_and_close_clear_ram(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=QSettings(str(Path(directory)/'settings.ini'),QSettings.Format.IniFormat)
            with (patch('ghost_box.ui.caspy.QSettings',return_value=settings),patch('ghost_box.ui.window.QSettings',return_value=settings),
                  patch('ghost_box.ui.window.QStandardPaths.writableLocation',return_value=directory),
                  patch('ghost_box.mail.gmail.saved_account',return_value=''),patch('ghost_box.mail.gmail.can_send',return_value=True),
                  patch('ghost_box.mail.gmail.send',return_value='sent-id') as send):
                owner=Window();owner.task.wait()
                for _ in range(15):self.app.processEvents()
                source=dict(id='one',thread_id='thread',message_id='<parent@example.com>',references='',sender='Ada <ada@example.com>',
                            recipients='me@example.com',cc='',subject='Budget',body='Please review the budget.')
                dialog=ComposeDialog(source,'me@example.com','reply',owner);self.drain(dialog)
                self.assertTrue(dialog.allowed)
                owner.language.setCurrentIndex(0)
                dialog.instructions.setPlainText('Bütçeyi onayladığımı söyle.')
                with (patch.object(owner,'model_configuration',return_value=(Path(directory),owner.caspy.parameters())),
                      patch.object(owner.runtime,'load') as load):
                    dialog.generate()
                self.assertEqual(load.call_args.kwargs['request']['language'],'Turkish')
                dialog.model_event(dict(kind='done',status='success'))
                dialog.body.setPlainText('Bütçe uygundur. Devam edebilirsiniz.')
                send.assert_not_called()
                with patch.object(QMessageBox,'exec',return_value=QMessageBox.StandardButton.Cancel):dialog.review_send()
                send.assert_not_called()
                with patch.object(QMessageBox,'exec',return_value=QMessageBox.StandardButton.Yes):dialog.review_send()
                self.drain(dialog)
                send.assert_called_once()
                payload=send.call_args.args[1]
                message=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(payload['raw']))
                self.assertIn('ada@example.com',message['To']);self.assertIn('Bütçe uygundur',message.get_body().get_content())
                self.assertTrue(dialog.locked)
                dialog.review_send();self.assertEqual(send.call_count,1)
                dialog.reject()
                self.assertFalse(dialog.source);self.assertEqual(dialog.body.toPlainText(),'')
                owner.close()
