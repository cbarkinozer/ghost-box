"""Email identity belongs to the application, even if the model repeats citations."""

import json
import unittest

from ghost_box.mail.summary import summarize, without_citations
from ghost_box.mail.tasks import TaskError


def mail(identifier, body):
    return dict(id=identifier, subject=identifier, timestamp=1, sender='Test', recipients='Test', body=body)


class SummaryTests(unittest.TestCase):
    def test_separate_emails_and_application_owned_sources(self):
        prompts, events, output = [], [], []
        def render(system, user):
            prompts.append(user)
            return user, 1
        def generate(prompt, maximum):
            yield 'A short summary. **Kaynak:** 3 [3] [Source 3](ghostmail:third)'
        messages = [mail('first', 'Job suggestion, no application submitted.'),
                    mail('second', 'Nightly build failed.'), mail('third', 'Network invitation.')]
        summarize(messages, 'Summarize', dict(max_input_tokens=1024, max_output_tokens=512, max_tasks=64),
                  render, generate, lambda done,total,phase: events.append((done,total)), output.append)
        for prompt in prompts:
            emails = json.loads(prompt.split('Selected emails (JSON):\n')[1])
            self.assertEqual(len(emails), 1)
        text = ''.join(output)
        for index, message in enumerate(messages, 1):
            self.assertEqual(text.count(f'[Source {index}](ghostmail:{message["id"]})'), 1)
        self.assertNotIn('Kaynak', text)
        self.assertNotIn('[3]', text)
        self.assertEqual(events[-1], (3, 3))

    def test_limit_is_enforced_and_accidental_citations_removed(self):
        with self.assertRaises(TaskError):
            summarize([mail('one','A'), mail('two','B')], 'Q', dict(max_tasks=1),
                      None, None, lambda *args: None, lambda text: None)
        for text in ('[2]', 'Source 2', '**Kaynak:** 2', '[Kaynak: **2**]', '[known-id]'):
            cleaned = without_citations(text, {'known-id'})
            self.assertNotIn('2', cleaned)
            self.assertNotIn('known-id', cleaned)
