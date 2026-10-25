"""Follow-ups use previous answers, bounded local tools, and streaming; no full-mail replay."""

import json
import unittest
from unittest.mock import patch

from ghost_box.mail.followup import follow_up, retrieve
from ghost_box.mail.tasks import TaskError
from ghost_box.models.worker import workflow

PARAMS = dict(max_input_tokens=7680, max_output_tokens=2048, max_tasks=8)


def mail(identifier, body, source):
    return dict(id=identifier, subject=f'Subject {identifier}', body=body, source=source,
                sender='sender@example.com', recipients='me@example.com', timestamp=1)


class FollowUpTests(unittest.TestCase):
    def run_followup(self, replies, question='What should I do?', previous='Payment failed.', messages=None, params=None):
        prompts, streamed, events, counts = [], [], [], []
        def render(system, user):
            prompts.append((system, json.loads(user)))
            return user, len(user) // 4
        def generate(prompt, maximum):
            counts.append(maximum)
            yield from replies.pop(0)
        request = dict(emails=messages or [mail('one','SECRET ORIGINAL FULL BODY',1)], question=question,
                       previous=dict(request='Summarize', answer=previous, partial=False), language='Turkish')
        follow_up(request, params or PARAMS, render, generate, lambda *args:None,
                  streamed.append, lambda *args: events.append(args))
        return prompts, streamed, events, counts

    def test_direct_answer_streams_without_original_email_body(self):
        prompts, streamed, events, counts = self.run_followup([['{"tool":"answer"}'], ['Ödeme ', 'yöntemini güncelleyin. [1]']])
        self.assertEqual(streamed, ['Ödeme ', 'yöntemini güncelleyin. [1]'])
        self.assertEqual(len(prompts), 2)
        self.assertNotIn('SECRET ORIGINAL FULL BODY', json.dumps(prompts))
        self.assertIn('Payment failed.', json.dumps(prompts))
        self.assertEqual(counts, [160, 512])
        self.assertIn('previous answer only', events[0][1])


    def test_answer_chunks_arrive_before_generation_finishes(self):
        streamed, calls = [], []
        def generate(prompt, maximum):
            calls.append(maximum)
            if len(calls) == 1:
                yield '{"tool":"answer"}'
            else:
                yield 'First chunk. '
                self.assertEqual(streamed, ['First chunk. '])
                yield 'Second chunk.'
        follow_up(dict(emails=[mail('one','Original body',1)],question='Explain',
                       previous=dict(answer='Summary')), PARAMS,
                  lambda system,user:(user,1),generate,lambda *args:None,streamed.append,lambda *args:None)
        self.assertEqual(streamed,['First chunk. ','Second chunk.'])

    def test_read_only_requested_id_then_stream_answer(self):
        messages = [mail('one','Please approve the budget by Friday.',1),mail('two','UNRELATED SECRET',2)]
        prompts, streamed, events, counts = self.run_followup(
            [[json.dumps(dict(tool='read_email',id='one'))],['Approve by Friday. [1]']],messages=messages)
        self.assertEqual(len(prompts),2)
        self.assertNotIn('Please approve',json.dumps(prompts[0]))
        self.assertIn('Please approve',json.dumps(prompts[1]))
        self.assertNotIn('UNRELATED SECRET',json.dumps(prompts))
        self.assertEqual(streamed,['Approve by Friday. [1]'])
        self.assertEqual(events[0][0],'search')

    def test_search_returns_only_bounded_relevant_passages(self):
        messages = [mail('one', 'Earlier material. ' * 300 + 'Needle invoice due on Friday. ' + 'Footer. '*300,1),
                    mail('two','UNRELATED SECRET',2)]
        result = retrieve(messages,dict(tool='search',query='needle',id='one'))
        self.assertEqual(len(result),1)
        self.assertIn('Needle invoice',result[0]['excerpt'])
        self.assertLess(len(result[0]['excerpt']),710)
        self.assertNotIn('UNRELATED SECRET',json.dumps(result))
        self.assertEqual(result[0]['source'],1)
        with self.assertRaises(TaskError):retrieve(messages,dict(tool='read_email',id='outside'))
        with self.assertRaises(TaskError):retrieve(messages,dict(tool='send',id='one'))

    def test_previous_answer_clips_to_measured_token_budget(self):
        prompts, streamed, events, counts = self.run_followup([['{"tool":"answer"}'],['Short answer.']],previous='Long answer. '*3000,
                                                             params=PARAMS | {'max_input_tokens':500})
        self.assertTrue(prompts[-1][1]['previous']['partial'])
        self.assertLess(len(prompts[-1][1]['previous']['answer']),2000)

    def test_invalid_tool_never_replays_full_mail(self):
        with self.assertRaises(TaskError):
            self.run_followup([['{"tool":"read_email","id":"outside"}']])

    def test_bm25_ask_only_supplies_matching_excerpts(self):
        class Backend:
            finish_reason = None
            def __init__(self):self.prompts=[];self.calls=0
            def render(self,system,user):self.prompts.append(user);return user,1
            def generate(self,prompt,maximum):
                self.calls+=1
                yield '{"query":"needle"}' if self.calls==1 else 'Found the invoice. [1]'
            def clear_request(self):pass
            def memory(self):return ''
        backend=Backend()
        request=dict(question='Where is the invoice?',use_search=True,
                     emails=[mail('one','Prefix. '*500+'Needle invoice due Friday.'+' Footer.'*500,1),
                             mail('two','UNRELATED SECRET',2)])
        with patch('ghost_box.models.worker.emit'):
            workflow(request,backend,PARAMS)
        self.assertEqual(backend.calls,2)
        self.assertNotIn('UNRELATED SECRET',' '.join(backend.prompts))
        self.assertIn('Needle invoice',backend.prompts[-1])
        self.assertLess(len(backend.prompts[-1]),2200)
