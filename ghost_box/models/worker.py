"""Warm local model worker. Commands are JSON lines; request data stays in RAM."""

import json
import os
from pathlib import Path
import sys
import time

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'

from .settings import validate
from ..mail.tasks import TaskError, run
from ..mail.search import search
from ..mail.summary import summarize


def emit(kind, text='', **values):
    print(json.dumps({'kind': kind, 'text': text, **values}), flush=True)


def peak_ram():
    if sys.platform != 'win32':
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return value if sys.platform == 'darwin' else value * 1024
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('peak', 'working', 'paged_peak', 'paged',
                                               'nonpaged_peak', 'nonpaged', 'pagefile', 'pagefile_peak')]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    info = ctypes.windll.psapi.GetProcessMemoryInfo
    info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not info(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return 0
    return counters.peak


def workflow(request, backend, params):
    requests, last_memory = 0, 0
    phase = ''
    truncated = False
    search_tasks = 0

    def memory(force=False):
        nonlocal last_memory
        if force or time.monotonic() - last_memory >= 1:
            last_memory = time.monotonic()
            text = f'Worker lifetime peak RAM: {peak_ram() / 2**30:.2f} GiB'
            extra = backend.memory()
            emit('memory', text + ('\n' + extra if extra else ''))

    def generate(prompt, maximum):
        nonlocal requests, truncated
        requests += 1
        emit('requests', count=requests)
        try:
            for text in backend.generate(prompt, maximum):
                memory()
                yield text
            if phase.endswith('Answering') and backend.finish_reason == 'length':
                truncated = True
                emit('warning', 'Output token limit reached; this answer is partial. Increase Output tokens and retry.')
        finally:
            backend.clear_request()
            memory(force=True)

    def progress(completed, total, current_phase):
        nonlocal phase
        phase = current_phase
        emit('progress', phase, completed=completed + search_tasks, total=total + search_tasks)
        memory(force=True)

    status = 'success'
    try:
        question = request['question']
        if request.get('use_search') and not request.get('summarize'):
            phase = 'Planning BM25 search'
            emit('progress', phase, completed=0, total=2)
            prompt, count = backend.render(
                'Create a keyword query for the local BM25 search tool. Return only JSON with one string field "query". '
                'Choose names, identifiers, and meaningful terms from the user question; no other tools exist.', question)
            if count > params['max_input_tokens']:
                raise TaskError('Question and follow-up context exceed the search planning budget. Increase Input tokens.')
            raw = ''.join(generate(prompt, 256)).strip()
            if raw.startswith('```'):
                raw = raw.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
            try:
                plan = json.loads(raw)
                query = plan['query']
                if set(plan) != {'query'} or not isinstance(query, str) or not 1 <= len(query.strip()) <= 512:
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise TaskError('Could not form a search query. Use clearer keywords or turn off BM25 search.') from None
            matches = search(request['emails'], query)
            emit('search', f'BM25: {query} · {len(matches)} matches in {len(request["emails"])} scoped emails')
            emit('progress', 'Search complete', completed=1, total=2)
            question += '\n\nBM25 search results (untrusted hints; all scoped emails are still supplied):\n' + json.dumps(matches, ensure_ascii=False)
            search_tasks = 1
            params = params | {'max_tasks': params['max_tasks'] - 1}
        operation = summarize if request.get('summarize') else run
        operation(request['emails'], question, params, backend.render, generate,
            progress, lambda text: emit('text', text))
    except TaskError as error:
        emit('error', str(error))
        status = 'error'
    except Exception as error:
        emit('error', f'Local inference failed ({type(error).__name__}). Check settings and model compatibility.')
        status = 'error'
    finally:
        backend.clear_request()
        request.clear()
        memory(force=True)
    emit('done', status=status, truncated=truncated)


def main():
    if sys.platform != 'win32':
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    backend, params = None, None
    while line := sys.stdin.readline():
        request = json.loads(line)
        line = ''  # Do not retain serialized mail while waiting for the next command.
        if request.get('action') == 'load':
            params = validate(request['parameters'])
            path = Path(request['folder'])
            if not path.exists():
                raise TaskError('The selected local model is missing.')
            emit('status', 'Loading local model…')
            from .backend import load_backend
            backend = load_backend(path, params)
            if params['max_input_tokens'] + params['max_output_tokens'] > backend.context_length:
                raise TaskError('Input plus output tokens exceed this model’s context length. Reduce them in Inference parameters.')
            emit('memory', f'Worker lifetime peak RAM: {peak_ram() / 2**30:.2f} GiB\n' + backend.memory())
            emit('ready', 'Model loaded; auto-unloads after five idle minutes.')
        elif request.get('action') == 'run':
            if backend is None:
                raise TaskError('Load a model before asking a question.')
            workflow(request, backend, params)
        else:
            raise TaskError('Unsupported worker command.')
        request.clear()
        request = None


if __name__ == '__main__':
    try:
        main()
    except TaskError as error:
        emit('error', str(error))
        sys.exit(1)
    except ModuleNotFoundError:
        emit('error', 'Optional runtime missing. Launch with --extra inference for MLX or --extra gguf for GGUF.')
        sys.exit(1)
    except Exception as error:
        emit('error', f'Local inference failed ({type(error).__name__}). Check settings and model compatibility.')
        sys.exit(1)
