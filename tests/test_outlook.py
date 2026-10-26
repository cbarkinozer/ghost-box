"""Graph mail transport: scopes, date boundaries, exclusions, safe paging and one-shot send."""

import base64
from datetime import datetime,timezone
from email import policy
from email.parser import BytesParser
import unittest
from unittest.mock import Mock,patch

from ghost_box.mail import outlook
from ghost_box.mail.errors import AccountError,SendError
from ghost_box.mail.store import MailStore


def item(identifier='one',folder='inbox',date='2026-10-25T10:00:00Z'):
    return dict(id=identifier,conversationId='conversation',receivedDateTime=date,from_={},
        **{'from':{'emailAddress':{'name':'Ada','address':'ada@example.com'}}},
        toRecipients=[dict(emailAddress=dict(address='me@example.com'))],ccRecipients=[],replyTo=[],
        internetMessageId='<source@example.com>',subject='Budget',body=dict(contentType='html',content='<p>Approve &amp; reply</p><script>PRIVATE_SCRIPT</script><img src="https://remote/pixel">'),
        isDraft=False,parentFolderId=folder,hasAttachments=False)


def response(data=None,status=200):
    result=Mock(status_code=status);result.json.return_value=data or {};return result


def folder_responses():
    return [response(dict(id='junk',childFolderCount=1)),response(dict(id='trash',childFolderCount=0)),
            response(dict(id='drafts',childFolderCount=0)),response(dict(value=[dict(id='junk-child',childFolderCount=0)]))]


class OutlookTests(unittest.TestCase):
    def test_paging_filtering_mime_safety_metadata_counts_and_coverage(self):
        good=item();good['hasAttachments']=True
        replies=folder_responses()+[
            response(dict(value=[item('junk','junk-child'),item('draft','drafts'),good],
                          **{'@odata.nextLink':outlook.GRAPH+'/me/messages?$skiptoken=next'})),
            response(dict(value=[dict(id='file',isInline=False),dict(id='logo',isInline=True)])),
            response(dict(value=[item('one'),item('sent','sentitems')]))]
        mailbox=MailStore();first=datetime(2026,10,25,9,tzinfo=timezone.utc);last=datetime(2026,10,25,10,tzinfo=timezone.utc)
        with (patch.object(outlook.auth,'access_token',return_value='PRIVATE_TOKEN'),patch.object(outlook.requests,'Session') as session,
              patch('builtins.open',side_effect=AssertionError('Mail fetch must not open files'))):
            http=session.return_value.__enter__.return_value;http.get.side_effect=replies
            result=outlook.fetch(first,last,mailbox,'me@example.com',lambda text:None,lambda:False)
        self.assertEqual(result,dict(count=2,cancelled=False))
        self.assertEqual(set(mailbox.accounts['me@example.com']),{'one','sent'})
        source=mailbox.accounts['me@example.com']['one']
        self.assertEqual(source['attachment_count'],1);self.assertEqual(source['body'],'Approve & reply')
        self.assertNotIn('PRIVATE_SCRIPT',source['body']);self.assertNotIn('pixel',source['body'])
        self.assertEqual(mailbox.coverage['me@example.com']['provider'],'outlook')
        self.assertIn('2026-10-25T10:01:00Z',http.get.call_args_list[4].kwargs['params']['$filter'])
        self.assertTrue(all(call.kwargs['allow_redirects'] is False for call in http.get.call_args_list))
        attachment=http.get.call_args_list[5]
        self.assertEqual(attachment.kwargs['params'],{'$select':'id,isInline'})

    def test_cancel_failure_and_foreign_next_link_keep_previous_mail(self):
        for mode in ('cancel','foreign','failure'):
            with self.subTest(mode=mode):
                mailbox=MailStore();mailbox.replace('me@example.com',[dict(id='previous')],dict(count=1))
                stop=[False]
                def progress(text):stop[0]=mode=='cancel'
                next_url='https://evil.example/steal' if mode=='foreign' else outlook.GRAPH+'/me/messages?$skiptoken=next'
                replies=folder_responses()+[response(dict(value=[item()],**{'@odata.nextLink':next_url}))]
                if mode=='failure':replies.append(response(status=403))
                with (patch.object(outlook.auth,'access_token',return_value='PRIVATE_TOKEN'),patch.object(outlook.requests,'Session') as session):
                    http=session.return_value.__enter__.return_value;http.get.side_effect=replies
                    args=(datetime(2026,10,25,tzinfo=timezone.utc),datetime(2026,10,25,23,59,tzinfo=timezone.utc),mailbox,'me@example.com',progress,lambda:stop[0])
                    if mode=='cancel':self.assertTrue(outlook.fetch(*args)['cancelled'])
                    else:
                        with self.assertRaises(AccountError) as caught:outlook.fetch(*args)
                        self.assertNotIn('PRIVATE_TOKEN',str(caught.exception))
                self.assertEqual(set(mailbox.accounts['me@example.com']),{'previous'})
                self.assertEqual(mailbox.coverage['me@example.com'],dict(count=1))
                self.assertFalse(any('evil.example' in call.args[0] for call in http.get.call_args_list))

    def test_mime_payload_and_send_use_reviewed_recipients_and_single_post(self):
        source=outlook.decode_message(item())
        draft=dict(to='Reviewed <reviewed@example.com>',cc='copy@example.com',subject='Budget',body='Onaylı metin.')
        payload=outlook.build_payload('me@example.com',source,'reply_all',draft)
        message=BytesParser(policy=policy.default).parsebytes(base64.b64decode(payload['mime']))
        self.assertEqual(message['In-Reply-To'],'<source@example.com>')
        self.assertIn('reviewed@example.com',message['To']);self.assertIn('Onaylı metin',message.get_body().get_content())
        self.assertEqual(payload['path'],'/me/sendMail')  # Edited recipients must not be expanded by replyAll.
        original=outlook.prepare(source,'me@example.com','reply_all')
        threaded=outlook.build_payload('me@example.com',source,'reply_all',original | {'body':'Reviewed body'})
        self.assertTrue(threaded['path'].endswith('/replyAll'))
        self.assertEqual(outlook.build_payload('me@example.com',source,'forward',draft)['path'],'/me/sendMail')
        for status in (202,403,500):
            with self.subTest(status=status),patch.object(outlook.auth,'access_token',return_value='PRIVATE_TOKEN') as token,patch.object(outlook.requests,'Session') as session:
                http=session.return_value.__enter__.return_value;http.post.return_value=response(status=status)
                if status==202:self.assertEqual(outlook.send('me@example.com',payload),'accepted')
                else:
                    with self.assertRaises(SendError) as caught:outlook.send('me@example.com',payload)
                    self.assertEqual(caught.exception.uncertain,status>=500)
                http.post.assert_called_once();token.assert_called_once_with('me@example.com',sending=True)
                self.assertFalse(http.post.call_args.kwargs['allow_redirects'])
        with patch.object(outlook.auth,'access_token',side_effect=AccountError('Grant Mail.Send')),patch.object(outlook.requests,'Session') as session:
            with self.assertRaises(AccountError):outlook.send('me@example.com',payload)
            session.assert_not_called()
