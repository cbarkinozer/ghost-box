"""BM25 ranking, Turkish casing, empty results, and explicit mail scope."""

import unittest
from ghost_box.mail.search import search


def mail(identifier, sender, subject, body):
    return dict(id=identifier, sender=sender, recipients='Team', subject=subject, body=body)


class SearchTests(unittest.TestCase):
    def test_ranking_names_and_scope(self):
        messages = [mail('invoice', 'İpek IŞIK', 'ACME invoice-123', 'Invoice approved.'),
                    mail('meeting', 'Ada', 'Weekly meeting', 'Project Atlas meeting.'),
                    mail('other', 'Team', 'News', 'Lunch on Monday.')]
        self.assertEqual(search(messages, 'ACME invoice-123')[0]['id'], 'invoice')
        self.assertEqual(search(messages, 'ipek ışık')[0]['id'], 'invoice')
        self.assertEqual(search(messages, 'unfindable'), [])
        self.assertEqual(search(messages[1:], 'ACME invoice-123'), [])
        self.assertEqual(search(messages, ''), [])
