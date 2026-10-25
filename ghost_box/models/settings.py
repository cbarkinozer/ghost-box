"""Generation profiles only: never store prompts, emails, or results here."""

import json
import math
from pathlib import Path

DEFAULT_FILE = Path(__file__).parent / "data" / "inference_defaults.json"
# Bounds also define the native UI controls. No arbitrary runtime kwargs.
FIELDS = {
    'temperature': ('Temperature', float, 0, 2),
    'top_p': ('Top-p', float, 0, 1),
    'top_k': ('Top-k', int, 0, 1000),
    'min_p': ('Min-p', float, 0, 1),
    'presence_penalty': ('Presence penalty', float, -2, 2),
    'repetition_penalty': ('Repetition penalty', float, 0.1, 2),
    'max_output_tokens': ('Output tokens', int, 64, 32768),
    'max_input_tokens': ('Input tokens / task', int, 1024, 32768),
    'max_tasks': ('Maximum tasks', int, 2, 256),
}


def validate(values):
    if set(values) != set(FIELDS):
        raise ValueError('Missing or unknown inference parameters')
    for key, (_, kind, lower, upper) in FIELDS.items():
        value = values[key]
        if (type(value) not in (int, float) or not math.isfinite(value)
                or not lower <= value <= upper or (kind is int and type(value) is not int)):
            raise ValueError(f'Invalid inference parameter: {key}')
    return values


def read_settings(path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_FILE.read_text(), encoding='utf-8')
    data = json.loads(path.read_text(encoding='utf-8'))
    validate(data['default'])
    for profile in data['profiles'].values():
        validate(data['default'] | profile)
    if data.get('schema_version', 1) < 2:
        profile = data['profiles'].setdefault('mlx-community/Qwen3.5-4B-MLX-4bit', {})
        if profile.get('max_output_tokens', data['default']['max_output_tokens']) == 512:
            profile['max_output_tokens'] = 2048
        data['schema_version'] = 2
        write_settings(path, data)
    return data


def parameters(path, model):
    data = read_settings(path)
    return validate(data['default'] | data['profiles'].get(model, {}))


def save(path, model, values):
    validate(values)
    data = read_settings(path)
    data['profiles'][model] = values
    write_settings(path, data)


def write_settings(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
