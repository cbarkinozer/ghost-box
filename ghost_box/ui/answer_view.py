"""Local Markdown answers with links restricted to this answer's source emails."""

from html import escape
import re
from urllib.parse import quote, unquote

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtWidgets import QTextBrowser


class LocalDocument(QTextDocument):
    def loadResource(self, resource_type, url):
        # An invalid result lets Qt fall back to loading a local file. Return a
        # valid blank image instead, without touching the requested URL.
        image = QImage(1, 1, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        return image


class AnswerView(QTextBrowser):
    source_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDocument(LocalDocument(self))
        self.sources = {}
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self.open_source)
        self.highlighted.connect(self.show_source_hint)

    def loadResource(self, resource_type, url):
        # Model output must never load local files or remote images/resources.
        return self.document().loadResource(resource_type, url)

    def source_id(self, url):
        if url.scheme() != 'ghostmail':
            return None
        identifier = unquote(bytes(url.toEncoded()).decode().partition(':')[2])
        return identifier if identifier in self.sources else None

    def open_source(self, url):
        identifier = self.source_id(url)
        if identifier is not None:
            self.source_clicked.emit(identifier)

    def show_source_hint(self, url):
        identifier = self.source_id(url)
        message = self.sources.get(identifier)
        self.setToolTip('<qt>' + escape(message['subject']) + '<br>' + escape(message['sender']) + '</qt>' if message else '')

    def render(self, markdown, link_citations=True):
        numbers = {identifier: index for index, identifier in enumerate(self.sources, 1)}
        aliases = {str(number): identifier for identifier, number in numbers.items()} | {identifier: identifier for identifier in numbers}

        def link(match):
            text = match.group(1).replace('**', '').replace('__', '').strip()
            label = 'Kaynak' if re.search(r'\bkaynak', match.group(0), re.IGNORECASE) else 'Source'
            text = re.sub(r'^(?:kaynaklar|kaynak|sources?)\s*[:：]?\s*', '', text, flags=re.IGNORECASE)
            references = re.split(r'\s*[,;]\s*', text)
            if not any(reference in aliases for reference in references):
                return match.group(0)
            return ' '.join(f'[{label} {numbers[aliases[reference]]}](ghostmail:{quote(aliases[reference], safe="")})'
                            if reference in aliases else reference for reference in references)

        if link_citations:
            markdown = re.sub(r'\[([^\]\n]+)\](?!\()', link, markdown)
        # Generated links begin with '[' and are excluded from this second pass.
        marker = r'(?:\*\*|__)?'
        pattern = (rf'(?<![\w\[])(?:\(\s*)?{marker}(?:kaynaklar|kaynak|sources?){marker}'
                   rf'\s*(?::|：|\s)\s*{marker}\s*(\d+(?:\s*[,;]\s*\d+)*)(?!\w){marker}(?:\s*\))?')
        if link_citations:
            markdown = re.sub(pattern, link, markdown, flags=re.IGNORECASE)
        self.document().setMarkdown(markdown, QTextDocument.MarkdownFeature.MarkdownDialectGitHub
                                    | QTextDocument.MarkdownFeature.MarkdownNoHTML)
        self.verticalScrollBar().setValue(0)

    def clear(self):
        super().clear()
        self.sources = {}
        self.setToolTip('')
