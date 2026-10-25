"""Observed headers and recipient roles; these are not model judgments."""

from email.utils import getaddresses


def addresses(value):
    return list(dict.fromkeys(address.casefold() for _, address in getaddresses([value or '']) if address))


def details(message, account):
    to = addresses(message.get('recipients', ''))
    cc = addresses(message.get('cc', ''))
    own = account.casefold()
    role = ('sent' if own and own in addresses(message.get('sender', '')) else
            'to' if own and own in to else 'cc' if own and own in cc else 'other')
    return {'role': role, 'to_count': len(to), 'cc_count': len(cc),
            'recipient_count': len(set(to + cc)), 'attachment_count': message.get('attachment_count', 0)}
