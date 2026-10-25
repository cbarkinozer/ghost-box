"""Real operation plans and states, including BM25 and cancellation; no extra model calls."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from ghost_box.mail.tasks import run
from ghost_box.mail.steps import Steps
from ghost_box.models.worker import workflow
from ghost_box.ui.window import prepare_qt_plugins
from ghost_box.ui.work_steps import WorkSteps


def mail(identifier, body):
    return dict(id=identifier, timestamp=1, sender='sender@example.com', recipients='me@example.com',
                subject='Synthetic', body=body)


class WorkStepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_qt_plugins()
        cls.app = QApplication.instance() or QApplication([])

    def test_all_batches_and_final_answer_are_planned_before_generation(self):
        events, calls = [], []
        steps = Steps(lambda kind, **value: events.append(value.copy()))
        def generate(prompt, maximum):
            planned = [event for event in events if event['state']=='pending']
            self.assertTrue(any(event['action']=='answer_combine' for event in planned))
            self.assertGreater(sum(event['action']=='question_extract' for event in planned),1)
            self.assertTrue(any(event['state']=='running' for event in events))
            calls.append(prompt)
            yield 'Short evidence [1].'
        run([mail('one','a'*2000),mail('two','b'*2000)],'Find invoices',
            dict(max_input_tokens=1600,max_output_tokens=128,max_tasks=64),
            lambda system,user:(system+'\n'+user,len(system+'\n'+user)),generate,
            lambda *args:None,lambda text:None,steps=steps)
        self.assertEqual(len(calls),len(steps.rows))
        self.assertTrue(all(row['state']=='done' for row in steps.rows.values()))
        self.assertEqual(list(steps.rows.values())[-1]['action'],'answer_combine')
        self.assertTrue(any(row['sources']==[1] for row in steps.rows.values()))

    def test_bm25_visibility_and_call_counts_with_and_without_search(self):
        class Backend:
            finish_reason='stop'
            def __init__(self,search):self.calls=0;self.search=search
            def render(self,system,user):return user,1
            def generate(self,prompt,maximum):
                self.calls+=1
                yield '{"query":"invoice"}' if self.search and self.calls==1 else 'Invoice found [1].'
            def clear_request(self):pass
            def memory(self):return ''
        for use_search in (False,True):
            with self.subTest(search=use_search):
                events=[];backend=Backend(use_search)
                request=dict(emails=[mail('one','Invoice 42 is due Friday.')],question='Find invoices',
                             language='Turkish',use_search=use_search)
                with patch('ghost_box.models.worker.emit',side_effect=lambda kind,text='',**value:events.append(dict(kind=kind,text=text,**value))):
                    workflow(request,backend,dict(max_input_tokens=7680,max_output_tokens=512,max_tasks=64))
                steps=[event for event in events if event['kind']=='step']
                self.assertEqual(backend.calls,2 if use_search else 1)
                self.assertEqual(any(event['action']=='bm25_search' for event in steps),use_search)
                if not use_search:
                    self.assertTrue(any(event['kind']=='search' and 'BM25 kullanılmadı' in event['text'] for event in events))
                latest={event['step_id']:event for event in steps}
                self.assertTrue(all(event['state']=='done' for event in latest.values()))

    def test_ui_order_history_restore_and_interrupted_states(self):
        view=WorkSteps()
        view.restore([], 'Turkish')
        view.update_step(dict(step_id=1,action='question_extract',sources=[1,2],state='running'))
        view.update_step(dict(step_id=2,action='answer_combine',sources=[],state='pending'))
        view.update_step(dict(step_id=3,action='evidence_combine',sources=[1,2],state='pending',before=2))
        self.assertEqual([row['step_id'] for row in view.rows],[1,3,2])
        view.finish('stopped')
        self.assertEqual([row['state'] for row in view.rows],['cancelled','skipped','skipped'])
        saved=[dict(row) for row in view.rows]
        view.restore([], 'English')
        self.assertFalse(view.rows)
        view.restore(saved,'Turkish')
        self.assertIn('Durduruldu',view.list.item(0).text())
        self.assertIn('Kaynak 1, 2',view.list.item(0).text())
        self.assertIn('Çalıştırılmadı',view.list.item(1).text())
        view.deleteLater()

    def test_failed_generation_does_not_mark_queued_steps_done(self):
        events=[]
        steps=Steps(lambda kind,**value:events.append(value.copy()))
        running=steps.add('search_query');queued=steps.add('bm25_search',[1])
        steps.set(running,'running');steps.finish('error')
        self.assertEqual(steps.rows[running]['state'],'failed')
        self.assertEqual(steps.rows[queued]['state'],'skipped')

    def test_followup_shows_actual_lookup_without_more_model_calls(self):
        for plan in ('{"tool":"answer"}', '{"tool":"read_email","id":"one"}',
                     '{"tool":"search","query":"invoice"}'):
            with self.subTest(plan=plan):
                class Backend:
                    finish_reason='stop'
                    def __init__(self):self.calls=0
                    def render(self,system,user):return user,1
                    def generate(self,prompt,maximum):
                        self.calls+=1
                        yield plan if self.calls==1 else 'The invoice is due Friday. [1]'
                    def clear_request(self):pass
                    def memory(self):return ''
                backend=Backend();events=[]
                with patch('ghost_box.models.worker.emit',side_effect=lambda kind,text='',**value:events.append(dict(kind=kind,**value))):
                    workflow(dict(emails=[mail('one','Invoice due Friday.')],question='What is due?',follow_up=True,
                                  previous=dict(answer='There is an invoice.')),
                             backend,dict(max_input_tokens=7680,max_output_tokens=512,max_tasks=64))
                rows={event['step_id']:event for event in events if event['kind']=='step'}
                self.assertEqual(backend.calls,2)
                self.assertTrue(all(row['state']=='done' for row in rows.values()))
                self.assertTrue(any(row['action']=='followup_route' for row in rows.values()))
                self.assertEqual(len(rows),2 if 'answer' in plan else 3)

    def test_summary_retries_are_visible_as_failed_then_new_steps(self):
        from ghost_box.mail.summary import summarize
        events=[];calls=[]
        steps=Steps(lambda kind,**value:events.append(value.copy()))
        summarize([mail('one','First original statement.'),mail('two','Second original statement.')], 'Summarize',
                  dict(max_input_tokens=7680,max_output_tokens=2048,max_tasks=8),
                  lambda system,user:(user,1),
                  lambda prompt,maximum:(calls.append(prompt) or iter(['not JSON'])),
                  lambda *args:None,lambda text:None,steps=steps)
        self.assertEqual(len(calls),3)
        self.assertEqual(sum(row['action']=='summary_retry' for row in steps.rows.values()),2)
        self.assertEqual(sum(row['state']=='failed' for row in steps.rows.values()),3)
        overview=next(row for row in steps.rows.values() if row['action']=='summary_overview')
        self.assertEqual(overview['state'],'done')
        self.assertEqual(sum(row['state']=='done' for row in steps.rows.values()),1)

    def test_failed_step_click_explains_fixed_reason_without_raw_output(self):
        view=WorkSteps();view.restore([], 'Turkish')
        view.update_step(dict(step_id=1,action='summary_extract',sources=[1],state='failed',reason='invalid_json'))
        texts=[]
        with patch('ghost_box.ui.work_steps.QMessageBox.open',new=lambda dialog:texts.append(dialog.text())):
            view.show_details(view.list.item(0))
        self.assertIn('JSON',texts[0])
        self.assertIn('Kaynak 1',texts[0])
        saved=[dict(row) for row in view.rows]
        view.restore(saved,'Turkish')
        self.assertEqual(view.rows[0]['reason'],'invalid_json')
        view.deleteLater()
