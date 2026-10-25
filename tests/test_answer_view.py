"""Markdown rendering must not load resources or navigate beyond answer sources."""

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtWidgets import QApplication

from ghost_box.ui.answer_view import AnswerView
from ghost_box.ui.window import prepare_qt_plugins


class AnswerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_qt_plugins()
        cls.app = QApplication.instance() or QApplication([])

    def test_markdown_sources_and_resource_blocking(self):
        view = AnswerView()
        view.sources = {'one': {'subject': 'Budget <private>', 'sender': 'Alice'}}
        opened = []
        view.source_clicked.connect(opened.append)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private.png'
            image = QImage(2, 2, QImage.Format.Format_RGB32)
            image.fill(0)
            image.save(str(path))
            url = QUrl.fromLocalFile(str(path))
            view.render(f'## Decision\n\n**Approved** [1]\n\n![blocked]({url.toString()})\n\n<b>raw HTML</b>')
            self.assertIn('ghostmail:one', view.toHtml())
            self.assertIn('Source 1', view.toPlainText())
            self.assertIn('<b>raw HTML</b>', view.toPlainText())
            blocked = view.document().resource(QTextDocument.ResourceType.ImageResource, url)
            self.assertEqual((blocked.width(), blocked.height()), (1, 1))
            self.assertFalse(view.openLinks())
            self.assertFalse(view.openExternalLinks())
            for target in ('https://example.com', 'file:///private', 'ghostmail:unknown'):
                view.open_source(QUrl(target))
            self.assertEqual(opened, [])
            view.open_source(QUrl('ghostmail:one'))
            self.assertEqual(opened, ['one'])
        view.clear()
        self.assertFalse(view.sources)

    def test_localized_citation_formats_and_unknown_numbers(self):
        view = AnswerView()
        view.sources = {'first': {'subject': 'First', 'sender': 'Test'},
                        'second': {'subject': 'Second', 'sender': 'Test'}}
        for text in ('kaynak:2', 'Kaynak: 2', '[Kaynak: 2]', '(Kaynak: 2)',
                     '**Kaynak:** 2', 'Kaynak: **2**', 'Source: 2', '[Source 2]', '[2]'):
            with self.subTest(text=text):
                view.render(text)
                self.assertIn('ghostmail:second', view.toHtml())
                self.assertNotIn('ghostmail:first', view.toHtml())
        view.render('Kaynaklar: 1, 2')
        self.assertIn('ghostmail:first', view.toHtml())
        self.assertIn('ghostmail:second', view.toHtml())
        for text in ('Kaynak: 21', 'Kaynak: 999', 'Invoice amount: 2'):
            with self.subTest(text=text):
                view.render(text)
                self.assertNotIn('ghostmail:', view.toHtml())
