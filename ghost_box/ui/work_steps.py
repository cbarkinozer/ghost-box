"""Compact RAM-only checklist of actual operations, independent of LLM-call counts."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QVBoxLayout, QWidget, QMessageBox

LABELS = {
    'search_query': ('BM25 için arama sözcüklerini belirle', 'Choose BM25 search terms'),
    'bm25_search': ('BM25 ile yerel maillerde ara', 'Search local emails with BM25'),
    'email_read': ('İlgili mailin metnini oku', 'Read the relevant email text'),
    'followup_route': ('Önceki yanıt yeterli mi, kaynak okumak gerekiyor mu belirle', 'Choose previous answer or a local lookup'),
    'followup_answer': ('Önceki yanıt ve varsa bulunan kanıtlarla cevapla', 'Answer from the previous reply and any retrieved evidence'),
    'answer_selected': ('Kaynak maillerden yanıt hazırla', 'Answer from source emails'),
    'question_extract': ('Soruyla ilgili bilgileri mail kesitlerinden çıkar', 'Extract question-related evidence from email excerpts'),
    'evidence_combine': ('Ara bulguları birleştir ve kısalt', 'Combine and shorten intermediate evidence'),
    'answer_combine': ('Bulguları birleştirip son yanıtı hazırla', 'Combine evidence into the final answer'),
    'summary_extract': ('Mail özetlerini çıkar ve alıntıları doğrula', 'Extract summaries and check quotations'),
    'summary_retry': ('Eksik/geçersiz özetleri yeniden dene', 'Retry missing or invalid summaries'),
    'summary_overview': ('Bulguları genel bakış için önceliklendir', 'Prioritize findings for the overview'),
    'overview_reduce': ('Genel bakış adaylarını kısalt', 'Reduce overview candidates'),
}
STATES = {
    'pending': ('○', 'Bekliyor', 'Pending'), 'running': ('▶', 'Çalışıyor', 'Running'),
    'done': ('✓', 'Tamamlandı', 'Done'), 'failed': ('✕', 'Başarısız', 'Failed'),
    'cancelled': ('■', 'Durduruldu', 'Stopped'), 'skipped': ('–', 'Çalıştırılmadı', 'Not run'),
}


from ..mail.diagnostics import CODES
REASONS = {code: (text, code.replace('_', ' ')) for code, text in CODES.items()}
REASONS.update({
    'task_failed': ('İşlem tamamlanamadı. Ana durum mesajı ve Diagnostics ayrıntılarını kontrol edin.', 'Operation failed; check the status message and Diagnostics.'),
    'stopped': ('İşlem kullanıcı tarafından durduruldu.', 'Stopped by the user.'),
    'not_run': ('Önceki bir hata veya durdurma nedeniyle bu adım çalıştırılmadı.', 'Not run after a prior failure or cancellation.'),
})

class WorkSteps(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows, self.language = [], 'English'
        self.error_text = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.setWordWrap(True)
        self.list.setSpacing(6)
        self.list.itemClicked.connect(self.show_details)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        layout.addWidget(self.list)
        self.restore([], 'English')

    def restore(self, rows, language, error_text=''):
        self.rows, self.language = [], language
        self.error_text = error_text
        for row in rows:
            self.update_step(row, render=False)
        self.render()
        self.list.show()

    def update_step(self, event, render=True):
        if event.get('action') not in LABELS or event.get('state') not in STATES or type(event.get('step_id')) is not int:
            return
        row = {key: event[key] for key in ('step_id', 'action', 'state')}
        row['reason'] = event.get('reason') if event.get('reason') in REASONS else None
        row['sources'] = [n for n in event.get('sources', []) if type(n) is int and n > 0][:256]
        existing = next((item for item in self.rows if item['step_id'] == row['step_id']), None)
        if existing is not None:
            existing.update(row)
        elif len(self.rows) < 1024:
            index = next((i for i, item in enumerate(self.rows) if item['step_id'] == event.get('before')), len(self.rows))
            self.rows.insert(index, row)
        if render:
            self.render()

    def render(self):
        tr = self.language == 'Turkish'

        done = sum(row['state'] == 'done' for row in self.rows)
        failed = sum(row['state'] == 'failed' for row in self.rows)
        suffix = f' · {failed} {"başarısız" if tr else "failed"}' if failed else ''
        self.title = ('İşlem adımları' if tr else 'Work steps')
        if self.rows:
            self.title += f' · {done}/{len(self.rows)}' + suffix
        self.list.clear()
        for index, row in enumerate(self.rows, 1):
            symbol, turkish, english = STATES[row['state']]
            text = f'{index}. {symbol} {LABELS[row["action"]][0 if tr else 1]}'
            sources = row['sources']
            if sources:
                shown = ', '.join(map(str, sources[:8])) + ('…' if len(sources) > 8 else '')
                text += f' · {"Kaynak" if tr else "Source"} {shown}'
            text += ' · ' + (turkish if tr else english)
            item = QListWidgetItem(text)
            item.setToolTip(text)
            item.setData(Qt.ItemDataRole.UserRole, row['step_id'])
            self.list.addItem(item)
            if row['state'] == 'running':
                self.list.scrollToItem(item)
        self.changed.emit()

    def show_details(self, item):
        identifier = item.data(Qt.ItemDataRole.UserRole)
        row = next(row for row in self.rows if row['step_id'] == identifier)
        tr = self.language == 'Turkish'
        reason = REASONS.get(row.get('reason'), ('Ayrıntılı neden kaydedilmedi; Diagnostics görünümünü kontrol edin.',
                                                   'No detailed reason was recorded; check Diagnostics.'))
        if row.get('reason') in (None, 'task_failed') and self.error_text:
            reason = (self.error_text, self.error_text)
        text = item.text() + '\n\n' + (reason[0 if tr else 1] if row['state'] in ('failed', 'cancelled', 'skipped') else
                  'Bu adımın durumu yukarıda gösteriliyor.' if tr else 'The operation status is shown above.')
        dialog = QMessageBox(self)
        dialog.setWindowTitle('İşlem ayrıntısı' if tr else 'Step details')
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(text)
        dialog.exec()

    def finish(self, status):
        for row in self.rows:
            if row['state'] == 'running':
                row['state'] = 'cancelled' if status == 'stopped' else 'failed'
                row['reason'] = 'stopped' if status == 'stopped' else 'task_failed'
            elif row['state'] == 'pending':
                row['state'] = 'skipped'
                row['reason'] = 'not_run'
        self.render()
