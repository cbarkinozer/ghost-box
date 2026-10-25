"""Illustrative full-attention KV-cache growth; never a total-RAM prediction."""

import json


def cache_bytes_per_token(folder):
    if folder is None or not folder.is_dir():
        return None
    try:
        config = json.loads((folder / 'config.json').read_text())
        config = config.get('text_config', config)
        layers = config.get('layer_types', [])
        if not layers or any(kind not in ('full_attention', 'linear_attention') for kind in layers):
            return None
        attention_layers = layers.count('full_attention')
        # Illustrative unquantized FP16/BF16 keys and values (2 bytes each).
        head_dim = config.get('head_dim') or config['hidden_size'] // config['num_attention_heads']
        return 2 * 2 * attention_layers * config['num_key_value_heads'] * head_dim
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def describe(folder, parameters):
    per_token = cache_bytes_per_token(folder)
    if not per_token:
        return ('Memory projection unavailable for this model. Load it to measure memory. '
                'More output tokens can increase cache use and generation time; weight size is unchanged.')
    tokens = parameters['max_input_tokens'] + parameters['max_output_tokens']
    return (f'Illustrative attention cache: ~{per_token * tokens / 2**20:,.0f} MiB at {tokens:,} tokens.\n'
            f'+1,024 output tokens ≈ +{per_token * 1024 / 2**20:,.0f} MiB of attention cache.\n'
            'Assumes FP16/BF16 cache at the full budget. Excludes weights, recurrent state, '
            'allocation padding, and workspaces; actual peak RAM varies. More output also takes longer.')
