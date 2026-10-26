"""Run the application's email workflows against fixed synthetic mail only."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent


def fixtures():
    mailbox = json.loads((ROOT / 'mailbox.json').read_text(encoding='utf-8'))
    cases = json.loads((ROOT / 'cases.json').read_text(encoding='utf-8'))['cases']
    return mailbox, cases


def smoke_checks(text, expected):
    """Lexical checks do not establish factual accuracy or language compliance."""
    folded = text.casefold()
    return {
        'required_terms': all(any(term.casefold() in folded for term in group)
                              for group in expected['term_groups']),
        'forbidden_terms_absent': not any(term.casefold() in folded for term in expected['forbidden']),
    }


def measure(backend, params, mailbox, case):
    from unittest.mock import patch
    from ghost_box.models.worker import workflow, peak_ram
    selected = [next(m for m in mailbox['emails'] if m['id'] == identifier).copy()
                for identifier in case['scope']]
    # Citation ordinals must match selection order, including follow-up snapshots.
    for ordinal, message in enumerate(selected, 1):
        message['source'] = ordinal
    request = dict(question=case['question'], emails=selected, language=case['language'],
                   account=mailbox['account'], summarize=case['kind'] == 'summary',
                   use_search=case['use_search'], follow_up=case['kind'] == 'follow_up',
                   previous=dict(request='Previous synthetic request', answer=case['previous'], partial=False))
    call_metrics = []
    class MeasuredBackend:
        def __getattr__(self, name):
            return getattr(backend, name)

        def generate(self, prompt, maximum):
            started = time.perf_counter()
            for text in backend.generate(prompt, maximum):
                yield text
            call_metrics.append(dict(getattr(backend, 'last_metrics', {})) |
                                {'call_elapsed_s': time.perf_counter() - started})

    started = time.perf_counter()
    events, chunks = [], []
    first_visible = None
    final_summary = None

    def collect(kind, text='', **values):
        nonlocal first_visible, final_summary
        if (kind == 'text' and text) or (kind == 'summary' and values.get('markdown')):
            if first_visible is None:
                first_visible = time.perf_counter() - started
        if kind == 'text':
            chunks.append(text)
        if kind == 'summary':
            final_summary = values.get('markdown', '')
        if kind in ('error', 'warning', 'diagnostic', 'requests', 'done', 'search', 'step'):
            events.append(dict(kind=kind, text=text, **values))

    with patch('ghost_box.models.worker.emit', side_effect=collect):
        workflow(request, MeasuredBackend(), params)
    answer = final_summary if final_summary is not None else ''.join(chunks)
    done = next((e for e in reversed(events) if e['kind'] == 'done'), {})
    return dict(status=done.get('status', 'error'), answer=answer,
                elapsed_s=time.perf_counter() - started, first_visible_s=first_visible,
                llm_calls=max((e['count'] for e in events if e['kind'] == 'requests'), default=0),
                peak_process_ram_bytes=peak_ram(), smoke_checks=smoke_checks(answer, case['expected']),
                expected=case['expected'], source_map={m['source']: m['id'] for m in selected},
                human_review=dict(factual_accuracy=None, correct_citations=None, correct_language=None,
                                  appropriate_refusal=None, omissions=None, notes='Not reviewed'),
                call_metrics=call_metrics, events=events)


def child(args):
    # Match the application worker's offline settings before loading model libraries.
    for key in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY'):
        os.environ[key] = '1'
    from ghost_box.models.backend import load_backend
    from ghost_box.models.settings import defaults, validate
    mailbox, cases = fixtures()
    case = next(c for c in cases if c['id'] == args.case)
    params = defaults(args.profile)
    if args.parameters:
        params = validate(json.loads(Path(args.parameters).read_text(encoding='utf-8')))
    started = time.perf_counter()
    backend = load_backend(Path(args.model).resolve(), params)
    load_s = time.perf_counter() - started
    if params['max_input_tokens'] + params['max_output_tokens'] > backend.context_length:
        raise ValueError('Input plus output budget exceeds model context length')
    runs = []
    for repeat in range(args.repeats):
        runs.append(measure(backend, params, mailbox, case) | dict(
            repeat=repeat + 1, temperature=params['temperature'],
            state='cold_first_request' if repeat == 0 else 'warm',
            model_load_s=load_s if repeat == 0 else 0,
            throughput_note='See per-call runtime metrics; null means unavailable. No character-based TPS estimate.'))
    return dict(case=case['id'], parameters=params, runs=runs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', help='Existing local MLX folder or GGUF file; never downloads')
    parser.add_argument('--model-id', default='custom-local')
    parser.add_argument('--revision', default='unrecorded', help='Exact source revision/hash for reproducibility')
    parser.add_argument('--profile', default='mlx-community/Qwen3.5-4B-MLX-4bit')
    parser.add_argument('--parameters', help='Optional JSON object with all numeric inference parameters')
    parser.add_argument('--case', help='Run one case, e.g. q06')
    parser.add_argument('--repeats', type=int, default=2, help='First request plus warm repeats per case')
    parser.add_argument('--timeout', type=int, default=300, help='Seconds per case, including load and repeats')
    parser.add_argument('--output', default='benchmarks/results/latest.json')
    parser.add_argument('--list', action='store_true', help='Review questions without loading a model')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    mailbox, cases = fixtures()
    if args.case:
        cases = [c for c in cases if c['id'] == args.case]
        if not cases:
            parser.error('Unknown case')
    if args.list:
        for case in cases:
            print(f"{case['id']} [{case['kind']}] {case['question']}\n  Expected: {case['expected']['answer']}")
        return
    if not args.model or not Path(args.model).exists():
        parser.error('--model must be an existing local model path')
    if args.repeats < 1 or args.timeout < 1:
        parser.error('--repeats and --timeout must be positive')
    if args.child:
        print(json.dumps(child(args), ensure_ascii=False))
        return
    packages = {}
    for name in ('mlx-lm', 'llama-cpp-python'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    digest = hashlib.sha256()
    for path in sorted((ROOT.parent / 'ghost_box').rglob('*.py')) + [ROOT / 'mailbox.json', ROOT / 'cases.json', Path(__file__)]:
        digest.update(str(path.relative_to(ROOT.parent)).encode())
        digest.update(path.read_bytes())
    report = dict(schema_version=1, synthetic_only=True, fixture_version=mailbox['version'],
                  workflow_sha256=digest.hexdigest(), model_id=args.model_id, revision=args.revision,
                  quantization='User must record in model-id/revision', device=platform.machine(),
                  os=platform.platform(), python=platform.python_version(), runtimes=packages,
                  seed=None, seed_note='Seed is not exposed by the shared application backend.', cases=[])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        command = [sys.executable, '-m', 'benchmarks.run', '--child', '--model', args.model,
                   '--case', case['id'], '--repeats', str(args.repeats), '--profile', args.profile]
        if args.parameters:
            command += ['--parameters', args.parameters]
        print(f"{case['id']}: running ({case['kind']})…", flush=True)
        try:
            process = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout,
                                     cwd=ROOT.parent)
            if process.returncode:
                result = dict(case=case['id'], status='error', error=process.stderr[-2000:])
            else:
                result = json.loads(process.stdout)
        except subprocess.TimeoutExpired:
            result = dict(case=case['id'], status='timeout', timeout_s=args.timeout)
        except ValueError:
            result = dict(case=case['id'], status='error', error='Invalid child report')
        report['cases'].append(result)
        # Only built-in synthetic fixtures are accepted; private mailbox paths are not an option.
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# Synthetic benchmark results', '',
             'Lexical checks are not accuracy scores. Review answers and sources in the JSON report.', '',
             '| Case | Status | Samples | Median workflow s | Median first-visible s | LLM calls |',
             '| --- | --- | --- | --- | --- | --- |']
    for case in report['cases']:
        runs = case.get('runs', [])
        successful = [r for r in runs if r['status'] == 'success']
        visible = [r['first_visible_s'] for r in successful if r['first_visible_s'] is not None]
        latency = f"{statistics.median(r['elapsed_s'] for r in successful):.2f}" if successful else '—'
        first = f'{statistics.median(visible):.2f}' if visible else '—'
        statuses = ', '.join(r['status'] for r in runs) or case.get('status', 'error')
        lines.append(f"| {case['case']} | {statuses} | {len(runs)} | {latency} | {first} | {', '.join(str(r['llm_calls']) for r in runs)} |")
    output.with_suffix('.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Review results: {output} and {output.with_suffix(".md")}')


if __name__ == '__main__':
    main()
