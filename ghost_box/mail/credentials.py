"""Native credential storage only. No plaintext or file-backed fallback."""

import sys


def credential_store():
    if sys.platform == 'darwin':
        from keyring.backends.macOS import Keyring
    elif sys.platform == 'win32':
        from keyring.backends.Windows import WinVaultKeyring as Keyring
    else:
        raise RuntimeError('Credential storage supports macOS and Windows only.')
    return Keyring()
