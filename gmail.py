"""Read-only Gmail sign-in. Tokens live in the OS credential store."""

import json
import sys
from datetime import timedelta
from functools import partial
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import AuthorizedSession, Request
from google.auth.exceptions import RefreshError

import mail_store
from mail_text import decode_message

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SERVICE = "ghost-box"
ACCOUNT = "gmail"
CLIENT_FILE = Path(__file__).with_name("oauth-client.json")


class AccountError(RuntimeError):
    """A safe diagnostic message that never includes an OAuth response."""


def check_profile_response(response):
    if response.status_code == 403:
        try:
            error = response.json().get("error", {})
            reasons = {
                item.get("reason")
                for item in error.get("errors", []) + error.get("details", [])
                if isinstance(item, dict)
            }
        except (ValueError, AttributeError, TypeError):
            reasons = set()
        for codes, message in (
            ({"SERVICE_DISABLED", "accessNotConfigured"}, "Gmail API is disabled in the OAuth client's Google Cloud project. Enable it there and retry."),
            ({"ACCESS_TOKEN_SCOPE_INSUFFICIENT", "insufficientPermissions"}, "Gmail read permission was not granted. Reconnect and approve the Gmail read-access permission."),
            ({"domainPolicy"}, "Your Workspace administrator blocks Gmail access for this application."),
        ):
            if reasons & codes:
                raise AccountError(message)
    response.raise_for_status()


def credential_store():
    # Choose native backends explicitly: never fall back to plaintext storage.
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring
    elif sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring as Keyring
    else:
        raise RuntimeError("Gmail credential storage supports macOS and Windows only.")
    return Keyring()


def saved_account() -> str:
    saved = credential_store().get_password(SERVICE, ACCOUNT)
    return json.loads(saved)["email"] if saved else ""


def connect(client_file: str | Path = CLIENT_FILE) -> str:
    with open(client_file, encoding="utf-8") as file:
        config = json.load(file)
    installed = config.get("installed", {})
    if (
        installed.get("auth_uri") != "https://accounts.google.com/o/oauth2/auth"
        or installed.get("token_uri") != "https://oauth2.googleapis.com/token"
    ):
        raise ValueError("This build requires an unmodified Google Desktop OAuth configuration.")

    flow = InstalledAppFlow.from_client_config(
        config, scopes=[SCOPE], autogenerate_code_verifier=True
    )
    flow.fetch_token = partial(flow.fetch_token, timeout=20)
    stage = "Google authorization / token exchange"
    try:
        credentials = flow.run_local_server(
            host="127.0.0.1", port=0, timeout_seconds=60,
            authorization_prompt_message="",
            success_message="Return to Ghost-box to check the connection result.",
            prompt="consent", access_type="offline",
        )
        if not credentials.refresh_token:
            raise AccountError("Google did not provide offline access. Please reconnect and grant Gmail read access.")
        stage = "Gmail profile check"
        with flow.authorized_session() as session:
            response = session.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/profile", timeout=20
            )
            check_profile_response(response)
            email = response.json()["emailAddress"]
        stage = "OS credential storage"
        credential_store().set_password(
            SERVICE, ACCOUNT,
            json.dumps({"email": email, "credentials": json.loads(credentials.to_json())}),
        )
        return email
    except AccountError:
        raise
    except Exception as error:
        # Exception text may contain codes, tokens, or response bodies. Show only
        # the operation, exception class, and an HTTP status when available.
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        detail = f"HTTP {status}" if isinstance(status, int) else type(error).__name__
        advice = {
            "Google authorization / token exchange": "Try signing in again and grant Gmail read access.",
            "Gmail profile check": "Check that Gmail API is enabled in the OAuth client's project and Gmail read access was granted.",
            "OS credential storage": "Allow Python/Ghost-box access to your OS credential store and check that it is unlocked.",
        }[stage]
        raise AccountError(f"{stage} failed ({detail}). {advice}") from None
    finally:
        flow.oauth2session.close()


def disconnect() -> str:
    store = credential_store()
    if store.get_password(SERVICE, ACCOUNT) is not None:
        store.delete_password(SERVICE, ACCOUNT)
    return ""


def time_bounds(first, last):
    """Local date/time inputs; include the entire displayed end minute."""
    if first > last:
        raise AccountError("From must be on or before To.")
    return (
        int(first.timestamp()),
        int((last + timedelta(minutes=1)).timestamp()),
    )


def fetch(first, last, path, account, progress, cancelled):
    lower, upper = time_bounds(first, last)
    count = 0
    db = None
    try:
        store = credential_store()
        saved = json.loads(store.get_password(SERVICE, ACCOUNT) or "{}")
        if saved.get("email") != account:
            raise AccountError("Your saved Gmail account changed. Reconnect before fetching.")
        credentials = Credentials.from_authorized_user_info(saved["credentials"], [SCOPE])
        if not credentials.valid:
            request = Request()
            try:
                credentials.refresh(partial(request, timeout=20))
            finally:
                request.session.close()
            saved["credentials"] = json.loads(credentials.to_json())
            store.set_password(SERVICE, ACCOUNT, json.dumps(saved))
        db = mail_store.open_database(path)
        # Delete and insert in one transaction. Closing without commit restores
        # the previous local mailbox on cancellation or any error.
        db.execute("DELETE FROM messages WHERE account = ?", (account,))
        with AuthorizedSession(credentials) as session:
            token = None
            while not cancelled():
                response = session.get(
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                    params={"q": f"after:{lower - 1} before:{upper} -in:spam -in:trash -in:drafts",
                            "maxResults": 100, **({"pageToken": token} if token else {})},
                    timeout=20,
                )
                check_profile_response(response)
                page = response.json()
                for item in page.get("messages", []):
                    if cancelled():
                        return {"count": count, "cancelled": True}
                    response = session.get(
                        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{item['id']}",
                        params={"format": "raw"}, timeout=20,
                    )
                    if response.status_code == 404:  # Removed from Gmail during fetch.
                        continue
                    check_profile_response(response)
                    data = response.json()
                    if lower * 1000 <= int(data["internalDate"]) < upper * 1000:
                        mail_store.save(db, account, decode_message(data))
                        count += 1
                        progress(f"Fetched {count} messages…")
                token = page.get("nextPageToken")
                if not token:
                    stopped = cancelled()
                    if not stopped:
                        db.commit()
                    return {"count": count, "cancelled": stopped}
        return {"count": count, "cancelled": True}
    except AccountError:
        raise
    except RefreshError:
        raise AccountError("Gmail access expired or was revoked. Disconnect and reconnect.") from None
    except Exception as error:
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        detail = f"HTTP {status}" if isinstance(status, int) else type(error).__name__
        raise AccountError(
            f"Fetch stopped after {count} messages ({detail}). "
            "Previous local emails were kept; this incomplete fetch was discarded."
        ) from None
    finally:
        if db is not None:
            db.close()
