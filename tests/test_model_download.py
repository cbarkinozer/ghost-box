"""Tiny offline downloads verify integrity, cancellation, and reuse."""

import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import model_download as models


class DownloadTests(unittest.TestCase):
    def test_verified_download_reuse_and_corruption(self):
        payload = b'synthetic model'
        manifest = {'repo': 'test/model', 'revision': 'pinned', 'files': [
            {'name': 'model.safetensors', 'size': len(payload),
             'algorithm': 'sha256', 'digest': hashlib.sha256(payload).hexdigest()}]}
        with tempfile.TemporaryDirectory() as directory, patch.object(models, 'MANIFEST', manifest), patch.object(models, 'TOTAL_BYTES', len(payload)), patch('model_download.urlopen') as network:
            folder = Path(directory)
            network.return_value = io.BytesIO(payload)
            models.download(folder, Mock(), lambda: False)
            self.assertTrue(models.ready(folder))
            network.reset_mock()
            models.download(folder, Mock(), lambda: False)
            network.assert_not_called()
            (folder / 'model.safetensors').write_bytes(b'x' * len(payload))
            network.return_value = io.BytesIO(b'x' * len(payload))
            with self.assertRaises(ValueError):
                models.download(folder, Mock(), lambda: False)
            self.assertFalse(models.ready(folder))
            self.assertFalse(list(folder.glob('*.part')))
            network.return_value = io.BytesIO(payload)
            stopped = [False]
            def progress(text):
                if text.startswith('Downloading'):
                    stopped[0] = True
            with self.assertRaises(models.DownloadCancelled):
                models.download(folder, progress, lambda: stopped[0])
            self.assertFalse(models.ready(folder))
            self.assertFalse(list(folder.glob('*.part')))
