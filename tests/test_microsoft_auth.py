"""Microsoft sign-in/cache/refresh without contacting Microsoft or the real OS store."""

from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from ghost_box.mail import microsoft_auth as auth
from ghost_box.mail.errors import AccountError

CONFIG=dict(client_id='11111111-1111-4111-8111-111111111111',tenant='common')


class Vault:
    def __init__(self):self.data={};self.fail=False
    def get_password(self,service,key):return self.data.get((service,key))
    def set_password(self,service,key,value):
        if len(value.encode('utf-16-le'))>2560:raise ValueError('Native Windows size limit')
        if self.fail and ':1' in key:raise OSError('PRIVATE_STORE_ERROR')
        self.data[service,key]=value
    def delete_password(self,service,key):self.data.pop((service,key),None)


@contextmanager
def setup():
    with tempfile.TemporaryDirectory() as directory:
        file=Path(directory)/'outlook-client.json';file.write_text(json.dumps(CONFIG))
        vault=Vault();app=Mock();cache=Mock()
        app.acquire_token_interactive.return_value=dict(access_token='PRIVATE_TOKEN',scope='User.Read Mail.Read')
        app.get_accounts.return_value=[dict(home_account_id='home-one')]
        cache.serialize.return_value=json.dumps(dict(refresh_token='PRIVATE_REFRESH_'*800))
        cache.has_state_changed=False
        with (patch.object(auth,'credential_store',return_value=vault),
              patch.object(auth,'_application',return_value=(app,cache)),patch.object(auth.requests,'Session') as session):
            http=session.return_value.__enter__.return_value
            http.get.return_value.status_code=200
            http.get.return_value.json.return_value=dict(id='user-one',mail='me@example.com')
            yield file,vault,app,cache,http


class MicrosoftAuthTests(unittest.TestCase):
    def test_login_chunks_native_cache_and_startup_does_not_use_network(self):
        with setup() as (file,vault,app,cache,http):
            self.assertEqual(auth.connect(file),'me@example.com')
            app.acquire_token_interactive.assert_called_once_with(scopes=auth._scopes(auth.READ_SCOPES),prompt='select_account',timeout=60,port=0)
            saved=json.loads(vault.data[auth.SERVICE,auth.ACCOUNT])
            self.assertGreater(saved['parts'],1)
            self.assertNotIn('PRIVATE_TOKEN',json.dumps(saved))
            self.assertFalse(auth.can_send('me@example.com'))
            http.reset_mock()
            self.assertEqual(auth.saved_account(),'me@example.com');http.get.assert_not_called()
            self.assertTrue(all(len(value.encode('utf-16-le'))<=2560 for value in vault.data.values()))
            vault.data[auth.SERVICE,'gmail']='Other provider token'
            auth.disconnect()
            self.assertEqual(vault.data,{(auth.SERVICE,'gmail'):'Other provider token'})

    def test_wrong_account_and_missing_permissions_do_not_overwrite_connection(self):
        with setup() as (file,vault,app,cache,http):
            auth.connect(file);original=vault.data.copy()
            app.acquire_token_interactive.return_value=dict(access_token='PRIVATE_TOKEN',scope='User.Read Mail.Read Mail.Send')
            http.get.return_value.json.return_value=dict(id='different',mail='other@example.com')
            with self.assertRaises(AccountError):auth.connect(file,allow_send=True,expected_account='me@example.com')
            self.assertEqual(vault.data,original)
            http.get.return_value.json.return_value=dict(id='user-one',mail='me@example.com')
            app.acquire_token_interactive.return_value=dict(access_token='PRIVATE_TOKEN',scope='User.Read Mail.Read')
            with self.assertRaises(AccountError):auth.connect(file,allow_send=True,expected_account='me@example.com')
            self.assertEqual(vault.data,original)
            app.acquire_token_interactive.return_value=dict(error='access_denied',error_description='PRIVATE_OAUTH_RESPONSE')
            with self.assertRaises(AccountError) as caught:auth.connect(file)
            self.assertNotIn('PRIVATE',str(caught.exception));self.assertEqual(vault.data,original)

    def test_silent_refresh_is_account_bound_and_send_is_explicit(self):
        with setup() as (file,vault,app,cache,http):
            auth.connect(file)
            app.acquire_token_silent.return_value=dict(access_token='PRIVATE_ACCESS',scope='User.Read Mail.Read')
            self.assertEqual(auth.access_token('me@example.com'),'PRIVATE_ACCESS')
            with self.assertRaises(AccountError):auth.access_token('me@example.com',sending=True)
            with self.assertRaises(AccountError):auth.access_token('other@example.com')
            app.acquire_token_interactive.return_value=dict(access_token='PRIVATE_TOKEN',scope='User.Read Mail.Read Mail.Send')
            auth.connect(file,allow_send=True,expected_account='me@example.com')
            self.assertTrue(auth.can_send('me@example.com'))
            app.acquire_token_silent.return_value=dict(access_token='NEW_ACCESS',scope='User.Read Mail.Read Mail.Send')
            cache.has_state_changed=True
            self.assertEqual(auth.access_token('me@example.com',sending=True),'NEW_ACCESS')
            app.acquire_token_silent.return_value=dict(error='invalid_grant',error_description='PRIVATE_REFRESH_ERROR')
            with self.assertRaises(AccountError) as caught:auth.access_token('me@example.com')
            self.assertNotIn('PRIVATE',str(caught.exception))

    def test_failed_chunk_write_retains_previous_index_and_cache(self):
        with setup() as (file,vault,app,cache,http):
            auth.connect(file);previous=vault.data.copy();vault.fail=True
            with self.assertRaises(AccountError):auth._write(vault,CONFIG | dict(email='me@example.com'),cache.serialize())
            self.assertEqual(vault.data,previous)

    def test_config_rejects_custom_authority_or_client_secret_style_setup(self):
        with self.assertRaises(AccountError):auth._config(CONFIG | {'tenant':'https://example.com/steal'})
        with self.assertRaises(AccountError):auth._config(CONFIG | {'client_id':'not-a-client-id'})
        with self.assertRaises(AccountError):auth.connect('/nonexistent/outlook-client.json')
