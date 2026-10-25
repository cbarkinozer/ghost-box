"""Batched evidence must match its own email; overview can only select known facts."""

import json
import unittest

from ghost_box.mail.summary import summarize, checked_items, card_markdown, markdown_text
from ghost_box.mail.tasks import TaskError


def mail(identifier, body):
    return dict(id=identifier, subject=identifier, timestamp=1, sender='a@example.com',
                recipients='me@example.com', cc='team@example.com', body=body)


class SummaryTests(unittest.TestCase):
    def test_batches_and_extractive_overview(self):
        prompts, events, published, output = [], [], [], []
        def render(system, user):
            return (system, user), 1
        def generate(prompt, maximum):
            system, user = prompt; prompts.append(prompt)
            if 'Extract facts' in system:
                items = json.loads(user.split('Selected emails (JSON):\n')[1].split('\nItem keys:')[0])
                yield json.dumps({'items': [dict(key=item['key'], kind='information', kind_quote=' '.join(span['text'] for span in item['passages']),
                    facts=[dict(text=item['subject'], quote=' '.join(span['text'] for span in item['passages']))]) for item in items]})
            else:
                facts = json.loads(user.split('Facts:\n')[1])
                yield json.dumps({'facts': [fact['id'] for fact in facts[:8]]})
        messages = [mail(str(i), f'Confirmed unique fact number {i}.') for i in range(20)]
        summarize(messages, 'Summary', dict(max_input_tokens=7680, max_output_tokens=2048, max_tasks=64),
                  render, generate, lambda d,t,p:events.append((d,t)), output.append,
                  publish=lambda kind,**values:published.append((kind,values)), account='me@example.com')
        # Short emails share calls; twenty do not require twenty calls.
        self.assertLess(len(prompts), 20)
        self.assertEqual(events[-1], (len(prompts), len(prompts)))
        final = [value for kind,value in published if kind == 'summary'][-1]
        self.assertTrue(final['complete'])
        self.assertEqual(len(final['cards']), 20)
        self.assertLess(final['markdown'].index('## Overview'), final['markdown'].index('## Email details'))
        for index,message in enumerate(messages, 1):
            self.assertIn(f'[Source {index}](ghostmail:{message["id"]})', final['markdown'])
        self.assertIn('mode=reply_all', final['markdown'])
        self.assertIn('To: 1', final['markdown'])

    def test_quote_must_belong_to_its_email(self):
        pieces = [mail('one', 'The first unique original statement.') | {'key':'1:1','source':1},
                  mail('two', 'A completely different original fact.') | {'key':'2:1','source':2}]
        wrong = {'items':[dict(key='1:1',kind='information',kind_quote=pieces[0]['body'],
                     facts=[dict(text='Wrong owner',quote=pieces[1]['body'])]),
                       dict(key='2:1',kind='unclear',kind_quote='',facts=[])]}
        with self.assertRaises(TaskError):
            checked_items(json.dumps(wrong), pieces)
        wrong['items'][0]['facts'][0]['quote'] = pieces[0]['body']
        self.assertEqual(len(checked_items(json.dumps(wrong), pieces)), 2)
        wrong['items'][0]['facts'][0]['quote']='        '
        with self.assertRaises(TaskError):
            checked_items(json.dumps(wrong), pieces)
        wrong['items'][0]['facts'][0]['quote']=pieces[0]['body']
        wrong['items'][1]['key']='1:1'
        with self.assertRaises(TaskError):
            checked_items(json.dumps(wrong), pieces)

    def test_invalid_batch_falls_back_without_inventing_facts(self):
        published, events = [], []
        summarize([mail('one','Original contents here.'),mail('two','Other original contents.')], 'Summary',
                  dict(max_input_tokens=1024,max_output_tokens=2048,max_tasks=8),
                  lambda system,user:(user,1), lambda prompt,maximum:iter(['not JSON']),
                  lambda d,t,p:events.append((d,t)), lambda text:None,
                  publish=lambda kind,**value:published.append((kind,value)))
        final=[value for kind,value in published if kind=='summary'][-1]
        self.assertTrue(all(not card['facts'] for card in final['cards']))
        self.assertTrue(any(kind=='warning' for kind,value in published))
        self.assertEqual(events[-1][0],events[-1][1])

    def test_overview_groups_facts_and_covers_missing_emails(self):
        messages = [mail('one', 'Payment declined. Amount due 869.99.'), mail('two', 'Newsletter about product market fit.')]
        cards = [dict(id='one', source=1, kind='action_requested', facts=[
            dict(id='1.1', text='Payment declined.', quote='Payment declined.'),
            dict(id='1.2', text='Amount due 869.99.', quote='Amount due 869.99.')]),
            dict(id='two', source=2, kind='unclear', facts=[])]
        markdown = card_markdown(cards, messages, ['1.1', '1.2'], '', 'Turkish', True)
        overview = markdown.split('## Mail bazında ayrıntılar')[0]
        self.assertEqual(overview.count('[Kaynak 1]'), 1)
        self.assertIn(r'Payment declined\. Amount due 869', overview)
        self.assertIn('[Kaynak 2]', overview)
        self.assertIn('1 mailin özeti çıkarılamadı', overview)
        self.assertIn('\n\n---\n\n', markdown)
        self.assertIn('Newsletter about product market fit', markdown)

    def test_empty_results_get_one_bounded_batch_retry(self):
        calls, published = [], []
        def generate(prompt, maximum):
            system, user = prompt
            calls.append(system)
            if 'Extract facts' in system:
                items = json.loads(user.split('Selected emails (JSON):\n')[1].split('\nItem keys:')[0])
                yield '\n'.join(json.dumps(dict(key=item['key'],kind='unclear',kind_quote='',facts=[])) for item in items)
            else:
                self.fail('No overview call needed without facts')
        summarize([mail('one', 'Newsletter original contents.'), mail('two','Job invitation original contents.')],
                  'Summary', dict(max_input_tokens=7680,max_output_tokens=2048,max_tasks=8),
                  lambda system,user:((system,user),1),generate,lambda *args:None,lambda text:None,
                  publish=lambda kind,**value:published.append((kind,value)))
        self.assertEqual(len(calls),2)
        final = [value for kind,value in published if kind=='summary'][-1]
        self.assertTrue(all(not card['facts'] for card in final['cards']))
        self.assertIn('2 emails could not be summarized', final['markdown'])

    def test_selected_language_reaches_every_extraction_and_retry(self):
        for language, text in [('Turkish', 'Ödeme bilgilerinizi güncelleyin.'),
                               ('English', 'Update your payment information.')]:
            with self.subTest(language=language):
                prompts, published = [], []
                quote = 'Please update your billing information.'
                def generate(prompt, maximum):
                    system, user = prompt
                    if 'Extract facts' in system:
                        prompts.append((system, user))
                        self.assertIn(f'Default response language: {language}', system)
                        self.assertIn(f'default language of EVERY text field is {language}', system)
                        self.assertIn(f'Default text language: {language}', user)
                        self.assertIn('never copy or translate passage text', system)
                        # Force a retry to check that language does not disappear.
                        facts = [] if len(prompts) == 1 else [dict(text=text, quote=quote)]
                        yield json.dumps(dict(key='1:1',kind='action_requested',kind_quote=quote,facts=facts))
                    else:
                        yield '{"facts":["1.1"]}'
                summarize([mail('one', quote)], 'Summarize',
                          dict(max_input_tokens=7680,max_output_tokens=2048,max_tasks=8),
                          lambda system,user:((system,user),1),generate,lambda *args:None,lambda text:None,
                          publish=lambda kind,**value:published.append((kind,value)),language=language)
                self.assertEqual(len(prompts),2)
                final = [value for kind,value in published if kind == 'summary'][-1]
                self.assertEqual(final['cards'][0]['facts'][0]['text'],text)
                self.assertEqual(final['cards'][0]['facts'][0]['quote'],quote)
                self.assertIn(markdown_text(text), final['markdown'])

    def test_numbered_evidence_uses_original_spans_without_tracking_urls(self):
        from ghost_box.mail.summary import passages
        body = 'Your payment was declined. https://example.com/?token=PRIVATE_TRACKING_TOKEN Please update your payment method.'
        spans = passages(body)
        self.assertNotIn('PRIVATE_TRACKING_TOKEN',json.dumps(spans))
        piece = mail('one',body) | {'key':'1:1','source':1,'passages':spans}
        raw = json.dumps(dict(key='1:1',kind='action_requested',text='Ödeme yönteminizi güncelleyin.',evidence=2))
        records = checked_items(raw,[piece])
        self.assertEqual(records[0]['facts'][0]['quote'],'Please update your payment method.')
        with self.assertRaises(TaskError):
            checked_items(json.dumps(dict(key='1:1',kind='information',text='Unsupported.',evidence=999)),[piece])

    def test_valid_record_survives_malformed_neighbor_and_only_missing_email_retries(self):
        calls,published=[],[]
        def generate(prompt,maximum):
            system,user=prompt
            if 'Extract facts' not in system:
                yield '{"facts":["1.1","2.1"]}';return
            items=json.loads(user.split('Selected emails (JSON):\n')[1].split('\nItem keys:')[0])
            calls.append([item['id'] for item in items])
            if len(calls)==1:
                yield json.dumps(dict(key=items[0]['key'],kind='information',text='İlk bildirim.',evidence=1))+'\n{"key":'
            else:
                self.assertEqual(len(items),1)
                self.assertIn('Previous output failed',user)
                yield json.dumps(dict(key=items[0]['key'],kind='information',text='İkinci bildirim.',evidence=1))
        summarize([mail('one','First original statement.'),mail('two','Second original statement.')], 'Summary',
                  dict(max_input_tokens=7680,max_output_tokens=2048,max_tasks=8),
                  lambda system,user:((system,user),1),generate,lambda *args:None,lambda text:None,
                  publish=lambda kind,**value:published.append((kind,value)),language='Turkish')
        self.assertEqual(calls,[['one','two'],['two']])
        final=[value for kind,value in published if kind=='summary'][-1]
        self.assertEqual([len(card['facts']) for card in final['cards']],[1,1])
        self.assertEqual(final['cards'][0]['facts'][0]['quote'],'First original statement.')
        self.assertTrue(any(kind=='diagnostic' and value['code']=='invalid_json' for kind,value in published))

    def test_duplicate_records_are_not_salvaged_as_valid_evidence(self):
        from ghost_box.mail.summary import passages
        piece=mail('one','Original statement here.') | {'key':'1:1','source':1}
        piece['passages']=passages(piece['body'])
        item=dict(key='1:1',kind='information',text='Bildirim.',evidence=1)
        errors=[]
        records=checked_items(json.dumps(item)+'\n'+json.dumps(item),[piece],on_error=errors.append)
        self.assertEqual(records,[])
        self.assertTrue(any(error.code=='duplicate_email_id' for error in errors))

    def test_complete_json_array_is_valid_without_weakening_identity_checks(self):
        from ghost_box.mail.summary import passages
        piece=mail('one','The original event was confirmed.') | {'key':'1:1','source':1}
        piece['passages']=passages(piece['body'])
        raw=json.dumps([dict(key='1:1',kind='information',text='Olay doğrulandı.',evidence=1)])
        self.assertEqual(len(checked_items(raw,[piece])),1)
        with self.assertRaises(TaskError):
            checked_items(raw.replace('1:1','other-email'),[piece])
