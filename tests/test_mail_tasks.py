"""Deterministic token-budget and task accounting checks, without a model."""

import unittest

from mail_tasks import TaskError, run, split_emails


def message(identifier, body):
    return dict(id=identifier, timestamp=1, sender='Test', recipients='Test', subject='Test', body=body)


class TaskTests(unittest.TestCase):
    def test_single_large_email_is_split_without_losing_characters(self):
        body = 'Türkçe🙂 mixed mail. ' * 100
        batches = split_emails([message('one', body)], lambda items: sum(len(m['body']) + 20 for m in items), 150, 64)
        pieces = [m for batch in batches for m in batch]
        self.assertEqual(''.join(m['body'] for m in pieces), body)
        self.assertTrue(all(m['id'] == 'one' for m in pieces))
        self.assertEqual([m['part'] for m in pieces], list(range(1, len(pieces) + 1)))
        with self.assertRaises(TaskError):
            split_emails([message('one', body)], lambda items: sum(len(m['body']) + 20 for m in items), 150, 2)
        # The cap counts model batches, not the number of selected emails.
        many = [message(str(i), 'x') for i in range(200)]
        groups = split_emails(many, lambda items: len(items) * 10, 100, 20)
        self.assertEqual(len(groups), 20)
        self.assertEqual(sum(len(group) for group in groups), 200)

    def test_direct_and_batched_questions_and_task_limits(self):
        def render(system, user):
            text = system + '\n' + user
            return text, len(text)
        def generate(prompt, maximum):
            self.assertLessEqual(len(prompt), 1600)
            yield 'Evidence [one] [two]'
        params = {'max_input_tokens': 1600, 'max_output_tokens': 128, 'max_tasks': 64}
        events, output = [], []
        progress = lambda done, total, phase: events.append((done, total, phase))
        run([message('one', 'Short')], 'Question', params, render, generate, progress, output.append)
        self.assertEqual(events[-1][:2], (1, 1))
        events.clear(); output.clear()
        run([message('one', 'a' * 2000), message('two', 'b' * 2000)], 'Question', params, render, generate, progress, output.append)
        self.assertGreater(events[-1][1], 2)
        self.assertEqual(events[-1][0], events[-1][1])
        self.assertEqual(output, ['Evidence [one] [two]'])
        with self.assertRaises(TaskError):
            run([message('one', 'a' * 2000)], 'Question', params | {'max_tasks': 2}, render, generate, progress, output.append)

    def test_hierarchical_reduction_and_non_shrinking_failure(self):
        events = []
        def render(system, user):
            return user, len(user)
        params = {'max_input_tokens': 500, 'max_output_tokens': 64, 'max_tasks': 64}
        # Fixed-length notes require several levels of combination.
        def generate(prompt, maximum):
            yield 'x' * 150
        run([message(str(i), 'a' * 180) for i in range(10)], 'Q', params, render, generate,
            lambda done,total,phase: events.append((done,total,phase)), lambda text: None)
        self.assertTrue(any('Additional' in phase for _,_,phase in events))
        self.assertEqual(events[-1][0], events[-1][1])
        with self.assertRaises(TaskError):
            run([message(str(i), 'a' * 180) for i in range(3)], 'Q', params, render,
                lambda prompt, maximum: iter(['x' * 420]), lambda *args: None, lambda text: None)
