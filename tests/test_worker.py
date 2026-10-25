"""Request cleanup and explicit truncation reporting without loading a model."""

import unittest
from unittest.mock import patch

from ghost_box.models.worker import workflow


class Backend:
    finish_reason = None
    cleared = 0

    def render(self, system, user):
        return user, 1

    def generate(self, prompt, maximum):
        yield 'Partial answer'
        self.finish_reason = 'length'

    def clear_request(self):
        self.cleared += 1

    def memory(self):
        return 'Synthetic measurement'


class WorkerTests(unittest.TestCase):
    def test_truncation_and_request_cleanup(self):
        backend = Backend()
        request = {'emails': [dict(id='one', timestamp=1, sender='Test', recipients='Test',
                                  subject='Synthetic', body='Private synthetic fixture')], 'question': 'Q'}
        events = []
        with patch('ghost_box.models.worker.emit', side_effect=lambda kind, text='', **values: events.append(dict(kind=kind,text=text,**values))):
            workflow(request, backend, dict(max_input_tokens=1024, max_output_tokens=64, max_tasks=64))
        self.assertEqual(request, {})
        self.assertGreater(backend.cleared, 0)
        self.assertTrue(any(event['kind'] == 'warning' and 'partial' in event['text'] for event in events))
        self.assertTrue(events[-1]['truncated'])
        self.assertEqual(events[-1]['status'], 'success')
        self.assertEqual([e['count'] for e in events if e['kind'] == 'requests'], [1])

    def test_bm25_tool_is_bounded_and_query_schema_is_validated(self):
        class SearchBackend(Backend):
            def __init__(self, bad=False):
                self.calls, self.bad = 0, bad
            def generate(self, prompt, maximum):
                self.calls += 1
                self.finish_reason = 'stop'
                yield ('{"query":"Atlas","tool":"unknown"}' if self.bad else '{"query":"Atlas"}') if self.calls == 1 else 'Owner is Ada [1].'
        for invalid in (False, True):
            backend = SearchBackend(invalid)
            request = {'emails': [dict(id='one', timestamp=1, sender='Test', recipients='Test',
                                      subject='Atlas', body='Atlas owner is Ada.')],
                       'question': 'Who owns Atlas?', 'use_search': True}
            events = []
            with patch('ghost_box.models.worker.emit', side_effect=lambda kind, text='', **values: events.append(dict(kind=kind,text=text,**values))):
                workflow(request, backend, dict(max_input_tokens=1024, max_output_tokens=64, max_tasks=2))
            self.assertEqual(request, {})
            self.assertEqual(events[-1]['status'], 'error' if invalid else 'success')
            if not invalid:
                self.assertEqual([event['count'] for event in events if event['kind'] == 'requests'], [1, 2])
                final_progress = [event for event in events if event['kind'] == 'progress'][-1]
                self.assertEqual((final_progress['completed'], final_progress['total']), (2, 2))
                self.assertTrue(any(event['kind'] == 'search' and '1 matches in 1 scoped' in event['text'] for event in events))
