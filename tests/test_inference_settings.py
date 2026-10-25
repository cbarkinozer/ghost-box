"""Validate per-model numeric profiles and reject broken configuration."""

import json
from pathlib import Path
import tempfile
import unittest

from ghost_box.models.settings import DEFAULT_FILE, parameters, save, validate
from ghost_box.models.download import PRESET


class SettingsTests(unittest.TestCase):
    def test_profile_roundtrip_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inference-settings.json'
            preset = parameters(path, PRESET)
            self.assertEqual((preset['temperature'], preset['top_p'], preset['top_k']), (0.7, 0.8, 20))
            self.assertEqual(preset['presence_penalty'], 1.5)
            self.assertEqual(preset['max_output_tokens'], 2048)
            save(path, '/custom/model.gguf', preset | {'temperature': 0.2})
            self.assertEqual(parameters(path, '/custom/model.gguf')['temperature'], 0.2)
            self.assertEqual(parameters(path, PRESET), preset)
            for change in ({'temperature': float('nan')}, {'max_tasks': True}, {'top_k': 1.5}, {'unknown': 1}):
                with self.assertRaises(ValueError):
                    validate(preset | change)
            path.write_text('{broken')
            with self.assertRaises(ValueError):
                parameters(path, PRESET)
            self.assertEqual(path.read_text(), '{broken')

    def test_legacy_output_limit_migration_preserves_custom_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            legacy = json.loads(DEFAULT_FILE.read_text())
            legacy.pop('schema_version')
            legacy['profiles'][PRESET]['max_output_tokens'] = 512
            legacy['profiles']['/custom/model'] = {'max_output_tokens': 128}
            path.write_text(json.dumps(legacy))
            self.assertEqual(parameters(path, PRESET)['max_output_tokens'], 2048)
            self.assertEqual(parameters(path, '/custom/model')['max_output_tokens'], 128)
            legacy['profiles'][PRESET]['max_output_tokens'] = 1111
            path.write_text(json.dumps(legacy))
            self.assertEqual(parameters(path, PRESET)['max_output_tokens'], 1111)
