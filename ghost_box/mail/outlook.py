"""Outlook/Exchange Online via Graph. Manual fetch, RAM-only messages, approved sending."""

import base64
import re
from datetime import datetime, timezone
from email.headerregistry import Address
from urllib.parse import quote, urlsplit

import requests

from . import microsoft_auth as auth
from .microsoft_auth import connect, disconnect, saved_account, can_send
from .errors import AccountError, SendError
from .dates import time_bounds
from .drafting import build_payload as mime_payload, prepare, parse_recipients
from .text import PlainHTML

NAME = 'Outlook'
GRAPH = auth.GRAPH


def _url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'graph.microsoft.com'
            or not parsed.path.startswith('/v1.0/') or parsed.fragment):
        raise AccountError('Microsoft returned an unexpected pagination URL; fetching stopped.')
    return url


def _check(response):
    if response.status_code == 401:
        raise AccountError('Outlook access expired or was revoked. Reconnect with Microsoft.')
    if response.status_code == 403:
        raise AccountError('Microsoft Graph denied access. Check Mail.Read consent, Exchange Online licensing and tenant policy.')
    if response.status_code == 429:
        raise AccountError('Microsoft throttled the request. Wait and Fetch again.')
    if not 200 <= response.status_code < 300:
        raise AccountError(f'Microsoft Graph request failed (HTTP {response.status_code}).')


def _get(http, url, params=None):
    response = http.get(_url(url), params=params, timeout=20, allow_redirects=False)
    _check(response)
    return response.json()


def _pages(http, url, params=None):
    seen = set()
    while url:
        if url in seen:
            raise AccountError('Microsoft repeated a pagination URL; fetching stopped.')
        seen.add(url)
        page = _get(http, url, params)
        yield from page.get('value', [])
        url, params = page.get('@odata.nextLink'), None


def _excluded_folders(http, cancelled):
    result, queue = set(), []
    for name in ('junkemail', 'deleteditems', 'drafts'):
        if cancelled():
            return result
        # Missing well-known folders are treated as errors, not silently included.
        queue.append(_get(http, GRAPH + '/me/mailFolders/' + name, {'$select': 'id,childFolderCount'}))
    while queue and not cancelled():
        folder = queue.pop()
        if folder['id'] in result:
            continue
        result.add(folder['id'])
        if folder.get('childFolderCount', 0):
            for child in _pages(http, GRAPH + '/me/mailFolders/' + quote(folder['id'], safe='') + '/childFolders',
                                {'$select': 'id,childFolderCount', 'includeHiddenFolders': 'true'}):
                if cancelled():
                    return result
                queue.append(child)
    return result


def _addresses(values):
    return ', '.join(str(Address(display_name=item.get('emailAddress', {}).get('name', ''),
                    addr_spec=item['emailAddress']['address'])) for item in values if item.get('emailAddress', {}).get('address'))


def decode_message(item, attachment_count=0):
    body = item.get('body') or {}
    text = body.get('content') or ''
    if body.get('contentType', '').casefold() == 'html':
        parser = PlainHTML(); parser.feed(text); text = ''.join(parser.text).strip()
    headers = {header['name'].casefold(): header['value'] for header in item.get('internetMessageHeaders', [])}
    received = datetime.fromisoformat(item['receivedDateTime'].replace('Z', '+00:00'))
    return dict(id=item['id'], thread_id=item.get('conversationId', ''), timestamp=int(received.timestamp() * 1000),
        sender=_addresses([item.get('from') or item.get('sender') or {}]),
        recipients=_addresses(item.get('toRecipients', [])), cc=_addresses(item.get('ccRecipients', [])),
        reply_to=_addresses(item.get('replyTo', [])), message_id=item.get('internetMessageId', ''),
        references=headers.get('references', ''), attachment_count=attachment_count,
        subject=item.get('subject') or '(no subject)', body=text, provider='outlook')


def fetch(first, last, mailbox, account, progress, cancelled, exclude_promotions=False):
    lower, upper = time_bounds(first, last)
    count, pending, seen = 0, [], set()
    if cancelled():
        return dict(count=0, cancelled=True)
    try:
        token = auth.access_token(account)
        with requests.Session() as http:
            http.headers.update({'Authorization': 'Bearer ' + token,
                'Prefer': 'outlook.body-content-type="text", IdType="ImmutableId"'})
            excluded = _excluded_folders(http, cancelled)
            first_utc = datetime.fromtimestamp(lower, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            last_utc = datetime.fromtimestamp(upper, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            fields = ('id,conversationId,receivedDateTime,from,sender,toRecipients,ccRecipients,replyTo,'
                      'internetMessageId,internetMessageHeaders,subject,body,hasAttachments,isDraft,parentFolderId')
            params = {'$filter': f'receivedDateTime ge {first_utc} and receivedDateTime lt {last_utc} and isDraft eq false',
                      '$select': fields, '$top': 50}
            items = _pages(http, GRAPH + '/me/messages', params)
            while not cancelled():
                item = next(items, None)
                if item is None:
                    break
                if item.get('isDraft') or item.get('parentFolderId') in excluded or item['id'] in seen:
                    continue
                attachments = 0
                if item.get('hasAttachments'):
                    for attachment in _pages(http, GRAPH + '/me/messages/' + quote(item['id'], safe='') + '/attachments',
                                             {'$select': 'id,isInline'}):
                        if cancelled():
                            return dict(count=count, cancelled=True)
                        attachments += not attachment.get('isInline', False)
                message = decode_message(item, attachments)
                if lower * 1000 <= message['timestamp'] < upper * 1000:
                    pending.append(message); seen.add(message['id']); count += 1
                    progress(f'Fetched {count} Outlook messages…')
            if cancelled():
                return dict(count=count, cancelled=True)
            mailbox.replace(account, pending, dict(first=first, last=last, exclude_promotions=False,
                completed_at=datetime.now(), count=count, provider='outlook'))
        return dict(count=count, cancelled=False)
    except AccountError as error:
        raise AccountError(f'Outlook fetch stopped after {count} messages. Previous mail/coverage kept. {error}') from None
    except Exception:
        raise AccountError(f'Outlook fetch failed after {count} messages. Check the connection and Microsoft permissions. Previous mail/coverage kept.') from None


def build_payload(account, source, mode, draft):
    payload = mime_payload(account, source, mode, draft)
    raw = base64.b64encode(base64.urlsafe_b64decode(payload['raw'])).decode('ascii')
    path = '/me/sendMail'
    defaults = prepare(source, account, mode)
    def addresses(text):
        return {address.casefold() for _, address in parse_recipients(text)}
    unchanged_recipients = all(addresses(draft[key]) == addresses(defaults[key]) for key in ('to', 'cc'))
    if mode != 'forward' and draft['subject'] == source['subject'] and unchanged_recipients:
        action = 'replyAll' if mode == 'reply_all' else 'reply'
        path = '/me/messages/' + quote(source['id'], safe='') + '/' + action
    return dict(path=path, mime=raw)


def send(account, payload):
    """Exactly one approved MIME POST. HTTP 202 means accepted, not delivery confirmed."""
    attempted = False
    try:
        token = auth.access_token(account, sending=True)
        path = payload['path']
        if not (path == '/me/sendMail' or re.fullmatch(r'/me/messages/[^/]+/(?:reply|replyAll)', path)):
            raise SendError('Unsupported Outlook sending action.')
        with requests.Session() as http:
            attempted = True
            response = http.post(_url(GRAPH + path), data=payload['mime'],
                headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'text/plain', 'Prefer': 'IdType="ImmutableId"'},
                timeout=20, allow_redirects=False)
            if response.status_code == 202:
                return 'accepted'
            if 400 <= response.status_code < 500:
                raise SendError(f'Outlook rejected sending (HTTP {response.status_code}). Check consent, recipients and tenant policy.')
            raise SendError('Outlook send result is unconfirmed. Check Sent Items before sending again.', uncertain=True)
    except AccountError:
        raise
    except Exception:
        if not attempted:
            raise SendError('Could not prepare Outlook sending. Nothing was submitted; reconnect and retry.') from None
        raise SendError('Outlook send result is unconfirmed. Check Sent Items before sending again; no retry was made.', uncertain=True) from None
