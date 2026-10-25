"""Transparent attention-cache arithmetic; no claim of exact total memory."""

import json
from pathlib import Path
import tempfile
import unittest

from ghost_box.models.projection import cache_bytes_per_token, describe


class ProjectionTests(unittest.TestCase):
    def test_hybrid_attention_projection_and_unknown_models(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'config.json').write_text(json.dumps({'text_config': {
                'layer_types': ['linear_attention'] * 24 + ['full_attention'] * 8,
                'num_key_value_heads': 4, 'head_dim': 256,
            }}))
            self.assertEqual(cache_bytes_per_token(folder), 32768)
            text = describe(folder, dict(max_input_tokens=7680, max_output_tokens=2048))
            self.assertIn('304 MiB', text)
            self.assertIn('+32 MiB', text)
            self.assertIn('Excludes', text)
            self.assertIsNone(cache_bytes_per_token(folder / 'unknown.gguf'))
