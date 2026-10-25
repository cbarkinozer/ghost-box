"""Sending requires a matching account and explicit send grant; no ambiguous retries."""

import json
import unittest
from unittest.mock import Mock, patch

from ghost_box.mail import gmail


class SendingTests(unittest.TestCase):
    def test_send_scope_account_and_single_post(self):
        with (patch('ghost_box.mail.gmail.credential_store') as backend,
              patch('ghost_box.mail.gmail.Credentials.from_authorized_user_info') as credentials,
              patch('ghost_box.mail.gmail.AuthorizedSession') as factory):
            saved=dict(email='me@example.com',credentials={},scopes=[gmail.SCOPE])
            store=backend.return_value;store.get_password.return_value=json.dumps(saved)
            with self.assertRaises(gmail.AccountError):gmail.send('me@example.com',{'raw':'synthetic'})
            factory.assert_not_called()
            saved['scopes'].append(gmail.SEND_SCOPE);store.get_password.return_value=json.dumps(saved)
            with self.assertRaises(gmail.AccountError):gmail.send('other@example.com',{'raw':'synthetic'})
            factory.assert_not_called()
            credentials.return_value.valid=True
            session=factory.return_value.__enter__.return_value
            session.post.return_value=Mock(status_code=200)
            session.post.return_value.json.return_value={'id':'sent-id'}
            self.assertEqual(gmail.send('me@example.com',{'raw':'synthetic'}),'sent-id')
            self.assertEqual(session.post.call_count,1)
            self.assertEqual(factory.call_args.kwargs['max_refresh_attempts'],0)
            session.post.reset_mock();session.post.side_effect=TimeoutError('PRIVATE_MESSAGE')
            with self.assertRaises(gmail.SendError) as error:gmail.send('me@example.com',{'raw':'synthetic'})
            self.assertTrue(error.exception.uncertain)
            self.assertNotIn('PRIVATE_MESSAGE',str(error.exception))
            self.assertEqual(session.post.call_count,1)
            session.post.side_effect=None;session.post.return_value.status_code=403
            with self.assertRaises(gmail.SendError) as error:gmail.send('me@example.com',{'raw':'synthetic'})
            self.assertFalse(error.exception.uncertain)
