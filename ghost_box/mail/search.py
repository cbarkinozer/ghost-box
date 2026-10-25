"""Small in-memory BM25 search over the explicitly supplied email scope."""

from collections import Counter
import math
import re
import unicodedata


def tokens(text):
    text = unicodedata.normalize('NFKC', text.casefold()).replace('\u0307', '').replace('ı', 'i')
    return re.findall(r'\w+', text)


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
            # Keep tool output compact; the full selected mail still accompanies the answer.
            results.append({'id': message['id'], 'source': message.get('source', source),
                            'subject': message['subject'], 'score': round(score, 4)})
    return sorted(results, key=lambda item: (-item['score'], item['id']))[:limit]
