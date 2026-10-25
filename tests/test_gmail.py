"""Account boundary checks; no real Google requests or OS credentials."""

import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from ghost_box.mail import gmail


class GmailTests(unittest.TestCase):
    def test_profile_denial_explains_known_reasons_without_exposing_body(self):
        for reason, expected in (
            ("SERVICE_DISABLED", "Gmail API is disabled"),
            ("ACCESS_TOKEN_SCOPE_INSUFFICIENT", "Gmail read permission was not granted"),
            ("domainPolicy", "Workspace administrator"),
        ):
            response = Mock(status_code=403)
            response.json.return_value = {"error": {
                "details": [{"reason": reason}], "message": "PRIVATE_RESPONSE",
            }}
            with self.assertRaises(gmail.AccountError) as failure:
                gmail.check_profile_response(response)
            self.assertIn(expected, str(failure.exception))
            self.assertNotIn("PRIVATE_RESPONSE", str(failure.exception))

    def test_restore_and_disconnect_are_local(self):
        with patch("ghost_box.mail.gmail.credential_store") as backend:
            store = backend.return_value
            store.get_password.return_value = json.dumps({"email": "test@example.com"})
            self.assertEqual(gmail.saved_account(), "test@example.com")
            self.assertEqual(gmail.disconnect(), "")
            store.delete_password.assert_called_once_with(gmail.SERVICE, gmail.ACCOUNT)

    def test_untrusted_endpoints_rejected_before_oauth(self):
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as file:
            json.dump({"installed": {"token_uri": "https://example.com/token"}}, file)
            file.flush()
            with patch("ghost_box.mail.gmail.InstalledAppFlow.from_client_config") as factory:
                with self.assertRaises(ValueError):
                    gmail.connect(file.name)
                factory.assert_not_called()

    def test_only_profile_is_requested_and_tokens_saved_after_success(self):
        config = {"installed": {
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }}
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as file:
            json.dump(config, file)
            file.flush()
            with (
                patch("ghost_box.mail.gmail.InstalledAppFlow.from_client_config") as factory,
                patch("ghost_box.mail.gmail.credential_store") as backend,
            ):
                flow = factory.return_value
                credentials = flow.run_local_server.return_value
                credentials.to_json.return_value = '{"refresh_token": "fake"}'
                session = flow.authorized_session.return_value.__enter__.return_value
                session.get.return_value.json.return_value = {"emailAddress": "test@example.com"}
                self.assertEqual(gmail.connect(file.name), "test@example.com")
                self.assertEqual(factory.call_args.kwargs["scopes"], [gmail.SCOPE])
                self.assertTrue(factory.call_args.kwargs["autogenerate_code_verifier"])
                session.get.assert_called_once_with(
                    "https://gmail.googleapis.com/gmail/v1/users/me/profile", timeout=20
                )
                backend.return_value.set_password.assert_called_once()
                flow.oauth2session.close.assert_called_once()

                backend.return_value.reset_mock()
                session.get.return_value.raise_for_status.side_effect = RuntimeError("denied")
                with self.assertRaisesRegex(gmail.AccountError, "Gmail profile check failed"):
                    gmail.connect(file.name)
                backend.return_value.set_password.assert_not_called()

                session.get.return_value.raise_for_status.side_effect = None
                backend.return_value.set_password.side_effect = RuntimeError("PRIVATE_TOKEN")
                with self.assertRaises(gmail.AccountError) as failure:
                    gmail.connect(file.name)
                self.assertIn("OS credential storage failed", str(failure.exception))
                self.assertNotIn("PRIVATE_TOKEN", str(failure.exception))

                flow.run_local_server.side_effect = RuntimeError("PRIVATE_AUTH_CODE")
                with self.assertRaises(gmail.AccountError) as failure:
                    gmail.connect(file.name)
                self.assertIn("Google authorization / token exchange failed", str(failure.exception))
                self.assertNotIn("PRIVATE_AUTH_CODE", str(failure.exception))


if __name__ == "__main__":
    unittest.main()


class SendAuthorizationTests(unittest.TestCase):
    def test_send_grant_is_opt_in_and_account_must_match(self):
        config={'installed':{'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token'}}
        with tempfile.NamedTemporaryFile(mode='w+',suffix='.json') as file:
            json.dump(config,file);file.flush()
            with (patch('ghost_box.mail.gmail.InstalledAppFlow.from_client_config') as factory,
                  patch('ghost_box.mail.gmail.credential_store') as backend):
                flow=factory.return_value;credentials=flow.run_local_server.return_value
                credentials.to_json.return_value='{"refresh_token":"fake"}'
                credentials.granted_scopes=[gmail.SCOPE,gmail.SEND_SCOPE]
                session=flow.authorized_session.return_value.__enter__.return_value
                session.get.return_value.json.return_value={'emailAddress':'me@example.com'}
                gmail.connect(file.name,allow_send=True,expected_account='me@example.com')
                self.assertEqual(factory.call_args.kwargs['scopes'],[gmail.SCOPE,gmail.SEND_SCOPE])
                stored=json.loads(backend.return_value.set_password.call_args.args[2])
                self.assertIn(gmail.SEND_SCOPE,stored['scopes'])
                backend.return_value.set_password.reset_mock()
                with self.assertRaises(gmail.AccountError):
                    gmail.connect(file.name,allow_send=True,expected_account='different@example.com')
                backend.return_value.set_password.assert_not_called()
                credentials.granted_scopes=[gmail.SCOPE]
                with self.assertRaises(gmail.AccountError):
                    gmail.connect(file.name,allow_send=True,expected_account='me@example.com')
                backend.return_value.set_password.assert_not_called()
