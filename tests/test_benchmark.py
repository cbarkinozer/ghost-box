"""Benchmark fixtures and measurements use synthetic data and shared workflows."""

import json
from datetime import datetime
import unittest

from benchmarks.run import fixtures, measure, smoke_checks

PARAMS = dict(max_input_tokens=7680, max_output_tokens=2048, max_tasks=8)


class ScriptedBackend:
    finish_reason = 'stop'
    last_metrics = {}

    def __init__(self, replies):
        self.replies = iter(replies)
        self.prompts = []

    def render(self, system, user):
        self.prompts.append(user)
        return user, 100

    def generate(self, prompt, maximum):
        self.last_metrics = dict(input_tokens=100, output_tokens=12, decode_tokens_per_s=20)
        yield next(self.replies)

    def clear_request(self):
        pass

    def memory(self):
        return ''


class BenchmarkTests(unittest.TestCase):
    def test_twenty_reviewable_cases_and_valid_synthetic_scope(self):
        mailbox, cases = fixtures()
        ids = {m['id'] for m in mailbox['emails']}
        self.assertEqual(len(mailbox['emails']), 24)
        self.assertEqual(len(cases), 20)
        self.assertEqual(len({c['id'] for c in cases}), 20)
        for case in cases:
            self.assertTrue(set(case['scope']) <= ids)
            self.assertTrue(set(case['expected']['sources']) <= set(case['scope']))
            self.assertTrue(case['expected']['answer'])
            self.assertTrue(case['human_review'])
        for message in mailbox['emails']:
            self.assertIn('.example', message['sender'])
            self.assertEqual(message['timestamp'], int(datetime.fromisoformat(message['date']).timestamp() * 1000))

    def test_followup_uses_previous_answer_without_body_replay_and_records_metrics(self):
        mailbox, cases = fixtures()
        case = next(c for c in cases if c['id'] == 'q19')
        backend = ScriptedBackend(['{"tool":"answer"}', 'Son ödeme tarihi 2 Kasım 2026. [1]'])
        result = measure(backend, PARAMS, mailbox, case)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['llm_calls'], 2)
        self.assertEqual(len(result['call_metrics']), 2)
        self.assertEqual(result['call_metrics'][0]['decode_tokens_per_s'], 20)
        self.assertIsNotNone(result['first_visible_s'])
        self.assertEqual(result['source_map'], {1: 'm04', 2: 'm19'})
        self.assertTrue(all(result['smoke_checks'].values()))
        self.assertIsNone(result['human_review']['factual_accuracy'])
        for prompt in backend.prompts:
            self.assertNotIn('Please arrange payment.', prompt)
        json.dumps(result)

    def test_followup_can_read_one_original_email(self):
        mailbox, cases = fixtures()
        case = next(c for c in cases if c['id'] == 'q20')
        backend = ScriptedBackend(['{"tool":"read_email","id":"m06"}', '29 Ekim tarihine kadar. [1]'])
        result = measure(backend, PARAMS, mailbox, case)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['llm_calls'], 2)
        self.assertNotIn('29 Ekim', backend.prompts[0])
        self.assertIn('29 Ekim', backend.prompts[1])
        self.assertTrue(any(e['kind'] == 'search' and 'read_email' in e['text'] for e in result['events']))

    def test_smoke_checks_do_not_claim_accuracy(self):
        result = smoke_checks('240 but invented facts', dict(term_groups=[['240']], forbidden=[]))
        self.assertTrue(result['required_terms'])
        self.assertNotIn('accuracy', result)
