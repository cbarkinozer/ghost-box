"""Content-free diagnostic records. No logging, files, hashes, or provider identities."""

import json

from .tasks import TaskError

CODES = {
    'call_complete': 'Model çağrısı tamamlandı (süre tokens/s ölçümü değildir).',
    'output_limit': 'Üretim çıktı token sınırına ulaştı.',
    'invalid_json': 'Model çıktısı geçerli/tam JSON değil.',
    'invalid_record': 'Kayıt biçimi beklenen şemaya uymuyor.',
    'unknown_email_id': 'Model beklenmeyen bir mail anahtarı döndürdü.',
    'duplicate_email_id': 'Aynı mail anahtarı birden fazla kez döndü.',
    'missing_email_id': 'İstenen maillerden biri çıktıda eksik.',
    'invalid_evidence': 'Seçilen kanıt numarası bu mailin metin parçalarından biri değil.',
    'invalid_facts': 'Bulgu listesi beklenen biçimde değil.',
    'invalid_kind': 'Sınıflandırma değeri izin verilenlerden değil.',
    'invalid_fact_text': 'Özet metni boş, çok uzun veya metin değil.',
    'quote_mismatch': 'Bulgu alıntısı kendi mail kesitinde bulunamadı veya geçersiz uzunlukta.',
    'empty_facts': 'Model bu mail için boş bulgu listesi döndürdü.',
    'classification_unclear': 'Model sınıflandırmayı belirsiz döndürdü.',
    'classification_quote_mismatch': 'Sınıflandırmayı destekleyen alıntı doğrulanamadı.',
    'batch_validated': 'Grubun kayıtları ve bulgu alıntıları doğrulandı; anlam doğruluğu garanti edilmez.',
    'retry_split': 'Reddedilen grup daha küçük gruplarla yeniden denenecek.',
    'retry_empty': 'Boş bulgular için tek ek toplu deneme planlandı.',
    'retry_budget_exhausted': 'Ek deneme için çağrı bütçesi kalmadı.',
    'overview_local': 'Genel bakış mevcut bulgulardan yerel kodla sıralandı; LLM çağrısı yapılmadı.',
    'overview_fallback': 'Genel bakış sıralaması doğrulanamadı; mevcut bulgular kullanıldı.',
}


class SummaryError(TaskError):
    def __init__(self, code, source=None, position=None):
        super().__init__(CODES[code])
        self.code, self.source, self.position = code, source, position


def safe_record(event):
    """Allow only app-owned codes and numeric fields, even if an event has raw text."""
    if (not isinstance(event.get('code'), str) or event['code'] not in CODES
            or not isinstance(event.get('stage'), str) or event['stage'] not in ('extraction', 'overview', 'generation')):
        return None
    record = {key: event[key] for key in ('stage', 'code')}
    for key in ('call', 'source', 'input_tokens', 'output_chars', 'elapsed_ms', 'position'):
        value = event.get(key)
        if type(value) is int and 0 <= value <= 10**12:
            record[key] = value
    sources = event.get('sources')
    if isinstance(sources, list):
        record['sources'] = [value for value in sources[:256] if type(value) is int and 1 <= value <= 10**6]
    return record


def report(records):
    lines = ['RAM-only diagnostics · current message · last 512 records',
             'Valid independent records are retained; only missing/invalid records are retried once. Sources list the batch scope.',
             'No subjects, addresses, message IDs, prompts, quotations or model output are included.', '']
    for record in records:
        safe = safe_record(record)
        if safe is not None:
            lines.append(json.dumps(safe, ensure_ascii=False) + ' — ' + CODES[safe['code']])
    return '\n'.join(lines)
