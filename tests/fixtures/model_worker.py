"""Synthetic subprocess fixture; no model, account, files, or network."""

import json
import sys
import time


def emit(kind, **values):
    print(json.dumps({'kind': kind, **values}), flush=True)


for line in sys.stdin:
    command = json.loads(line)
    if command['action'] == 'load':
        emit('ready')
    elif command['action'] == 'run':
        time.sleep(0.08)
        emit('requests', count=1)
        emit('text', text='Synthetic answer')
        emit('done', status='success')
