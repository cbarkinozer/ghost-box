"""Microsoft public-client OAuth. Token cache lives only in native credential entries."""

import json
from pathlib import Path
from uuid import UUID, uuid4

import requests

from .credentials import credential_store
from .errors import AccountError

SERVICE, ACCOUNT = 'ghost-box', 'outlook'
CLIENT_FILE = Path(__file__).resolve().parents[2] / 'outlook-client.json'
READ_SCOPES = ['User.Read', 'Mail.Read']
SEND_SCOPE = 'Mail.Send'
GRAPH = 'https://graph.microsoft.com/v1.0'


def _config(values):
    try:
        client_id = str(UUID(values['client_id']))
        if UUID(client_id).int == 0:
            raise ValueError()
        tenant = values.get('tenant', 'common')
        if tenant not in ('common', 'organizations', 'consumers'):
            tenant = str(UUID(tenant))
        return dict(client_id=client_id, tenant=tenant)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise AccountError('Configure outlook-client.json with a Microsoft application client_id and tenant (common or your tenant ID).') from None


def _saved(store):
    raw = store.get_password(SERVICE, ACCOUNT)
    if not raw:
        return {}
    try:
        saved = json.loads(raw)
        UUID(saved['generation'])
        if type(saved['parts']) is not int or not 1 <= saved['parts'] <= 256:
            raise ValueError()
        return saved
    except (ValueError, KeyError, TypeError, AttributeError):
        raise AccountError('Stored Outlook credentials could not be read. Disconnect and reconnect.') from None


def _erase(store, saved):
    for index in range(saved.get('parts', 0)):
        key = f"outlook:{saved['generation']}:{index}"
        if store.get_password(SERVICE, key) is not None:
            store.delete_password(SERVICE, key)


def _write(store, metadata, cache):
    # Windows Credential Manager limits each secret's size. ASCII chunks use at
    # most 2,000 UTF-16 bytes; no cache file or plaintext fallback is involved.
    cache = json.dumps(json.loads(cache))
    parts = [cache[i:i + 1000] for i in range(0, len(cache), 1000)]
    if len(parts) > 256:
        raise AccountError('The Microsoft token cache exceeds the supported credential-store size.')
    old = _saved(store)
    saved = metadata | dict(generation=uuid4().hex, parts=len(parts))
    try:
        for index, part in enumerate(parts):
            store.set_password(SERVICE, f"outlook:{saved['generation']}:{index}", part)
        # Switch the index only after every new encrypted OS-store entry exists.
        store.set_password(SERVICE, ACCOUNT, json.dumps(saved))
    except Exception:
        try:
            _erase(store, saved)
        except Exception:
            pass
        raise AccountError('Could not save Microsoft credentials. Check native credential-store permissions.') from None
    _erase(store, old)


def saved_account():
    return _saved(credential_store()).get('email', '')


def disconnect():
    store = credential_store()
    saved = _saved(store)
    if saved:
        _erase(store, saved)
        store.delete_password(SERVICE, ACCOUNT)
    return ''


def can_send(account):
    saved = _saved(credential_store())
    return saved.get('email', '').casefold() == account.casefold() and SEND_SCOPE in saved.get('scopes', [])


def _application(config, http, serialized=None):
    from msal import PublicClientApplication, SerializableTokenCache
    cache = SerializableTokenCache()
    if serialized is not None:
        cache.deserialize(serialized)
    app = PublicClientApplication(config['client_id'], authority='https://login.microsoftonline.com/' + config['tenant'],
        token_cache=cache, http_client=http, timeout=20, instance_discovery=False, enable_pii_log=False)
    return app, cache


def _scopes(scopes):
    return ['https://graph.microsoft.com/' + scope for scope in scopes]


def connect(client_file=CLIENT_FILE, allow_send=False, expected_account=None):
    try:
        config = _config(json.loads(Path(client_file).read_text(encoding='utf-8')))
    except OSError:
        raise AccountError('Microsoft sign-in is not configured. Ask the maintainer for outlook-client.json; see the Outlook setup in README.') from None
    except ValueError:
        raise AccountError('outlook-client.json is not valid JSON. Use the provided example and your Microsoft app registration values.') from None
    scopes = READ_SCOPES + ([SEND_SCOPE] if allow_send else [])
    try:
        with requests.Session() as http:
            app, cache = _application(config, http)
            result = app.acquire_token_interactive(scopes=_scopes(scopes), prompt='select_account', timeout=60, port=0)
            if not isinstance(result, dict) or not result.get('access_token'):
                raise AccountError('Microsoft sign-in was cancelled, timed out or denied. Check app registration and tenant consent, then retry.')
            granted = {scope.rsplit('/', 1)[-1].casefold() for scope in result.get('scope', '').split()}
            if not {scope.casefold() for scope in scopes}.issubset(granted):
                raise AccountError('Required Outlook permissions were not granted. The saved connection was not changed.')
            response = http.get(GRAPH + '/me', params={'$select': 'id,mail,userPrincipalName'},
                                headers={'Authorization': 'Bearer ' + result['access_token']}, timeout=20, allow_redirects=False)
            if response.status_code != 200:
                raise AccountError(f'Microsoft profile check failed (HTTP {response.status_code}). Check User.Read consent and tenant policy.')
            profile = response.json()
            email = profile.get('mail') or profile.get('userPrincipalName') or ''
            accounts = app.get_accounts()
            if '@' not in email or not profile.get('id') or len(accounts) != 1:
                raise AccountError('Microsoft did not return one usable mail account. Check the Outlook/Exchange Online mailbox.')
            store = credential_store()
            old = _saved(store)
            if expected_account and (email.casefold() != expected_account.casefold()
                    or (old and old.get('user_id') != profile['id'])):
                raise AccountError('Sign in with the same Outlook account; the saved connection was not changed.')
            metadata = config | dict(email=email, user_id=profile['id'], home_id=accounts[0]['home_account_id'], scopes=scopes)
            _write(store, metadata, cache.serialize())
            return email
    except AccountError:
        raise
    except Exception:
        raise AccountError('Microsoft sign-in failed. Check the desktop app registration, tenant policy, connection and native credential-store permissions.') from None


def access_token(account, sending=False):
    try:
        store = credential_store()
        saved = _saved(store)
        if saved.get('email', '').casefold() != account.casefold():
            raise AccountError('The saved Outlook account changed. Reconnect before continuing.')
        if sending and SEND_SCOPE not in saved.get('scopes', []):
            raise AccountError('Outlook sending is not enabled. Approve Mail.Send from the compose window first.')
        chunks = [store.get_password(SERVICE, f"outlook:{saved['generation']}:{index}") for index in range(saved['parts'])]
        if any(part is None for part in chunks):
            raise AccountError('The Outlook token cache is incomplete. Disconnect and reconnect.')
        with requests.Session() as http:
            app, cache = _application(_config(saved), http, ''.join(chunks))
            accounts = [item for item in app.get_accounts() if item['home_account_id'] == saved['home_id']]
            if len(accounts) != 1:
                raise AccountError('The cached Outlook account could not be matched. Reconnect.')
            scopes = READ_SCOPES + ([SEND_SCOPE] if sending else [])
            result = app.acquire_token_silent(_scopes(scopes), account=accounts[0])
            if not result or not result.get('access_token'):
                raise AccountError('Outlook access expired, was revoked or needs consent. Reconnect with Microsoft.')
            granted = {scope.rsplit('/', 1)[-1].casefold() for scope in result.get('scope', '').split()}
            if not {scope.casefold() for scope in scopes}.issubset(granted):
                raise AccountError('Outlook permissions changed. Reconnect and grant the requested access.')
            if cache.has_state_changed:
                _write(store, saved, cache.serialize())
            return result['access_token']
    except AccountError:
        raise
    except Exception:
        raise AccountError('Could not refresh Outlook access. Check the connection and native credential store, or reconnect.') from None
