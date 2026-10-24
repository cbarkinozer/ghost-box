"""Validate per-model numeric profiles and reject broken configuration."""

import json
from pathlib import Path
import tempfile
import unittest

from inference_settings import parameters, save, validate
from model_download import PRESET


class SettingsTests(unittest.TestCase):
    def test_profile_roundtrip_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inference-settings.json'
            preset = parameters(path, PRESET)
            self.assertEqual((preset['temperature'], preset['top_p'], preset['top_k']), (0.7, 0.8, 20))
            self.assertEqual(preset['presence_penalty'], 1.5)
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
