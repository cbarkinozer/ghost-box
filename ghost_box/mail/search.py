"""Small in-memory BM25 search over the explicitly supplied email scope."""

from collections import Counter
import math
import re
import unicodedata


def folded(text):
    return unicodedata.normalize('NFKC', text.casefold()).replace('\u0307', '').replace('ı', 'i')


def tokens(text):
    return re.findall(r'\w+', folded(text))


def search(messages, query, limit=5):
    terms = set(tokens(query))
    documents = []
    frequency = Counter()
    for index, message in enumerate(messages, 1):
        text = ' '.join(str(message[key]) for key in ('id', 'sender', 'recipients', 'subject', 'body'))
        counts = Counter(tokens(text))
        documents.append((message, index, counts, sum(counts.values())))
        frequency.update(terms.intersection(counts))
    average = sum(length for _, _, _, length in documents) / max(1, len(documents))
    results = []
    for message, source, counts, length in documents:
        score = 0.0
        for term in terms.intersection(counts):
            inverse = math.log1p((len(documents) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            count = counts[term]
            score += inverse * count * 2.5 / (count + 1.5 * (0.25 + 0.75 * length / max(1, average)))
        if score:
            # Keep ranked results compact; callers choose the bounded excerpts to supply.
            results.append({'id': message['id'], 'source': message.get('source', source),
                            'subject': message['subject'], 'score': round(score, 4)})
    return sorted(results, key=lambda item: (-item['score'], item['id']))[:limit]


def matches(message, query, field='all'):
    """Literal, case-insensitive inbox filtering; no model or search index."""
    fields = ('sender', 'recipients', 'cc', 'subject', 'body', 'id') if field == 'all' else (field,)
    return any(folded(query) in folded(str(message.get(key, ''))) for key in fields)
