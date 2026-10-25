"""Tiny offline downloads verify integrity, cancellation, and reuse."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ghost_box.models import download as models


class DownloadTests(unittest.TestCase):
    def test_verified_download_reuse_and_corruption(self):
        payload = b'synthetic model'
        manifest = {'repo': 'test/model', 'revision': 'pinned', 'files': [
            {'name': 'model.safetensors', 'size': len(payload),
             'algorithm': 'sha256', 'digest': hashlib.sha256(payload).hexdigest()}]}
        with tempfile.TemporaryDirectory() as directory, patch.object(models, 'MANIFEST', manifest), patch.object(models, 'TOTAL_BYTES', len(payload)), patch('ghost_box.models.download.urlopen') as network:
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

    def test_gguf_manifest_controls_url_integrity_and_completion_marker(self):
        payload=b'GGUF synthetic payload'
        manifest=dict(repo='test/gguf',revision='pinned-gguf',files=[dict(
            name='Qwen_Qwen3.5-4B-Q4_K_M.gguf',size=len(payload),algorithm='sha256',
            digest=hashlib.sha256(payload).hexdigest())])
        with tempfile.TemporaryDirectory() as directory, patch('ghost_box.models.download.urlopen') as network:
            folder=Path(directory);network.return_value=io.BytesIO(payload)
            models.download(folder,Mock(),lambda:False,manifest)
            self.assertIn('/test/gguf/resolve/pinned-gguf/',network.call_args.args[0])
            self.assertTrue(models.ready(folder,manifest))
            self.assertFalse(models.ready(folder))
            network.reset_mock()
            models.download(folder,Mock(),lambda:False,manifest)
            network.assert_not_called()

    def test_remove_preset_refuses_custom_files_links_and_wrong_identity(self):
        payload=b'GGUF synthetic'
        manifest=dict(repo='test/preset',revision='pinned',files=[dict(name='model.gguf',size=len(payload),
                     algorithm='sha256',digest=hashlib.sha256(payload).hexdigest())])
        with tempfile.TemporaryDirectory() as directory, patch.dict(models.PRESETS,{'test/preset':manifest}):
            root=Path(directory)/'models';folder=root/'pinned';folder.mkdir(parents=True)
            file=folder/'model.gguf';file.write_bytes(payload)
            marker=folder/'download-complete.json';marker.write_text(json.dumps(manifest))
            private=folder/'custom-notes.txt';private.write_text('User-owned file')
            with self.assertRaises(ValueError):models.remove_preset(root,'test/preset')
            self.assertTrue(file.exists());private.unlink()
            with self.assertRaises(ValueError):models.remove_preset(root,'/custom/model.gguf')
            marker.write_text('{}')
            with self.assertRaises(ValueError):models.remove_preset(root,'test/preset')
            self.assertTrue(file.exists());marker.unlink()
            # Symlink refusal must happen before any file is removed.
            outside=Path(directory)/'custom.gguf';outside.write_bytes(payload)
            file.unlink()
            try:
                file.symlink_to(outside)
            except OSError:  # Windows may disallow symlinks without Developer Mode.
                pass
            else:
                with self.assertRaises(ValueError):models.remove_preset(root,'test/preset')
                self.assertEqual(outside.read_bytes(),payload)
                file.unlink()
            file.write_bytes(payload)
            models.remove_preset(root,'test/preset')
            self.assertFalse(folder.exists());self.assertEqual(outside.read_bytes(),payload)
