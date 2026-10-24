"""One bounded local workflow over stdin/stdout; exit unloads the model."""

import json
import os
from pathlib import Path
import sys
import time

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'

from inference_settings import validate
from mail_tasks import TaskError, run


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


def main():
    if sys.platform != 'win32':
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    request = json.loads(sys.stdin.readline())
    params = validate(request['parameters'])
    path = Path(request['folder'])
    if not path.exists():
        raise TaskError('The selected local model is missing.')
    emit('status', 'Loading local model…')
    from inference_backend import load_backend
    backend = load_backend(path, params)
    if params['max_input_tokens'] + params['max_output_tokens'] > backend.context_length:
        raise TaskError('Input plus output tokens exceed this model’s context length. Reduce them in Inference parameters.')
    last_memory = 0

    def memory(force=False):
        nonlocal last_memory
        if force or time.monotonic() - last_memory >= 1:
            last_memory = time.monotonic()
            text = f'Worker peak RAM: {peak_ram() / 2**30:.2f} GiB'
            extra = backend.memory()
            emit('memory', text + ('\n' + extra if extra else ''))

    def generate(prompt, maximum):
        for text in backend.generate(prompt, maximum):
            memory()
            yield text
        memory(force=True)

    def progress(completed, total, phase):
        emit('progress', phase, completed=completed, total=total)
        memory(force=True)

    memory(force=True)
    run(request['emails'], request['question'], params, backend.render, generate,
        progress, lambda text: emit('text', text))


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
