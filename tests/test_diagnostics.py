"""Specific failure reasons and privacy: no content enters diagnostic records."""

import json
import unittest
from unittest.mock import patch

from ghost_box.mail.diagnostics import SummaryError, safe_record, report
from ghost_box.mail.summary import checked_items, summarize
from ghost_box.models.worker import workflow


class DiagnosticsTests(unittest.TestCase):
    def piece(self):
        return dict(id='PRIVATE_PROVIDER_ID',key='1:1',source=1,subject='PRIVATE_SUBJECT',
                    sender='private@example.com',recipients='me@example.com',timestamp=1,
                    body='PRIVATE_BODY: the payment was declined.')

    def test_exact_rejection_codes_without_model_content(self):
        piece = self.piece()
        good = dict(key='1:1',kind='information',kind_quote=piece['body'],
                    facts=[dict(text='A payment was declined.',quote=piece['body'])])
        cases = [('PRIVATE_RAW not json','invalid_json'),
                 (json.dumps(good | {'key':'PRIVATE_UNKNOWN_ID'}),'unknown_email_id'),
                 (json.dumps(good)+'\n'+json.dumps(good),'duplicate_email_id'),
                 ('{"items":[]}', 'missing_email_id'),
                 (json.dumps(good | {'kind':'PRIVATE_KIND'}),'invalid_kind'),
                 (json.dumps(good | {'facts':[dict(text='PRIVATE_SUMMARY',quote='PRIVATE_WRONG_QUOTE')]}),'quote_mismatch')]
        for raw, code in cases:
            with self.subTest(code=code), self.assertRaises(SummaryError) as caught:
                checked_items(raw, [piece])
            self.assertEqual(caught.exception.code,code)
            self.assertNotIn('PRIVATE_',str(caught.exception))
            if code == 'invalid_json':self.assertIsInstance(caught.exception.position,int)

    def test_safe_fields_are_allowlisted_not_redacted_free_text(self):
        event=dict(stage='extraction',code='quote_mismatch',call=3,source=2,sources=[1,2,'PRIVATE_ID'],
                   input_tokens=1200,elapsed_ms=400,output_chars=300,text='PRIVATE_RAW',prompt='PRIVATE_PROMPT',
                   subject='PRIVATE_SUBJECT',body='PRIVATE_BODY',message_id='PRIVATE_ID',exception='PRIVATE_EXCEPTION')
        safe=safe_record(event)
        self.assertEqual(safe['sources'],[1,2])
        self.assertNotIn('PRIVATE_',json.dumps(safe))
        self.assertNotIn('PRIVATE_',report([event]))
        self.assertIsNone(safe_record(event | {'code':'PRIVATE_UNKNOWN_CODE'}))
        self.assertIsNone(safe_record(event | {'code':{'PRIVATE':'VALUE'}}))

    def test_batch_retry_empty_classification_and_overview_reasons(self):
        first = self.piece()
        second = first | {'id':'PRIVATE_OTHER_ID','subject':'PRIVATE_OTHER_SUBJECT','body':'PRIVATE_OTHER_BODY: invoice is due.'}
        calls, events = [], []
        def render(system,user):return (system,user),123
        def generate(prompt,maximum):
            system,user=prompt;calls.append(prompt)
            if 'Extract facts' not in system:
                yield 'PRIVATE_BAD_OVERVIEW';return
            items=json.loads(user.split('Selected emails (JSON):\n')[1].split('\nItem keys:')[0])
            if len(items)>1:
                yield 'PRIVATE_BAD_JSON';return
            item=items[0]
            if item['source']==1:
                yield json.dumps(dict(key=item['key'],kind='information',kind_quote=' '.join(span['text'] for span in item['passages']),
                                      facts=[dict(text='PRIVATE_SUMMARY',quote='PRIVATE_WRONG_QUOTE')]))
            else:
                yield json.dumps(dict(key=item['key'],kind='information',kind_quote='PRIVATE_WRONG_KIND_QUOTE',
                                      facts=[dict(text='PRIVATE_SUMMARY',quote=' '.join(span['text'] for span in item['passages']))]))
        summarize([first,second],'PRIVATE_QUESTION',dict(max_input_tokens=2048,max_output_tokens=2048,max_tasks=12),
                  render,generate,lambda *args:None,lambda text:None,
                  publish=lambda kind,**value:events.append((kind,value)))
        diagnostics=[value for kind,value in events if kind=='diagnostic']
        codes={row['code'] for row in diagnostics}
        self.assertTrue({'invalid_json','retry_split','quote_mismatch',
                         'classification_quote_mismatch','overview_local'} <= codes)
        self.assertEqual(len([row for row in diagnostics if row['code']=='call_complete']),len(calls))
        self.assertNotIn('PRIVATE_',report(diagnostics))
        self.assertNotIn('private@example.com',report(diagnostics))
        fault=next(row for row in diagnostics if row['code']=='quote_mismatch')
        self.assertEqual(fault['source'],1)
        self.assertEqual(fault['call'],2)

    def test_worker_reports_output_limit_without_raw_output(self):
        class Backend:
            finish_reason='length'
            def render(self,system,user):return user,1
            def generate(self,prompt,maximum):yield 'PRIVATE_RAW_OUTPUT'
            def clear_request(self):pass
            def memory(self):return ''
        events=[]
        request=dict(emails=[self.piece()],question='PRIVATE_QUESTION',summarize=True)
        with patch('ghost_box.models.worker.emit',side_effect=lambda kind,text='',**values:events.append((kind,values))):
            workflow(request,Backend(),dict(max_input_tokens=1024,max_output_tokens=64,max_tasks=8))
        diagnostics=[value for kind,value in events if kind=='diagnostic']
        self.assertTrue(any(row['code']=='output_limit' and row['call']==1 for row in diagnostics))
        self.assertNotIn('PRIVATE_',report(diagnostics))
        self.assertEqual(request,{})
