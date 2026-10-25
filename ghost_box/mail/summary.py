"""Summarize emails independently; application code owns source attribution."""

import re
from urllib.parse import quote

from .context import SUMMARY_SYSTEM
from .tasks import TaskError, run


def markdown_text(text):
    text = ' '.join(text.split())
    return re.sub(r'([\\`*_{}\[\]()<>#+.!|:])', r'\\\1', text)


def without_citations(text, identifiers=()):
    # Source links belong to the application heading, never to generated prose.
    text = re.sub(r'\[([^\]\n]*)\]\(ghostmail:[^)\n]*\)', r'\1', text)
    text = re.sub(r'<?ghostmail:[^\s<>)]*>?', '', text, flags=re.IGNORECASE)
    label = r'(?:sources?|kaynak(?:lar)?)'
    text = re.sub(rf'\[(?:{label}\s*:?\s*)?\d+(?:\s*[,;]\s*\d+)*\]', '', text, flags=re.IGNORECASE)
    marker = r'(?:\*\*|__)?'
    text = re.sub(rf'{marker}\b{label}{marker}\s*:?\s*{marker}\s*\d+(?:\s*[,;]\s*\d+)*(?!\w){marker}', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[([^\]\n]*)\]', lambda match: '' if match.group(1).strip() in identifiers else match.group(0), text)
    text = re.sub(r'\[\s*\]', '', text)
    return text.strip()


def summarize(messages, question, params, render, generate, progress, stream):
    count, completed = len(messages), 0
    total = count
    if count > params['max_tasks']:
        raise TaskError(f'Per-email summaries require at least {count} calls. Increase Maximum tasks or select fewer emails.')
    progress(0, total, 'Creating independent email summaries')
    for index, message in enumerate(messages, 1):
        local_total, local_done = 1, 0

        def report(done, tasks, phase):
            nonlocal total, local_total, local_done
            total += tasks - local_total
            local_total, local_done = tasks, done
            progress(completed + done, total, f'Email {index}/{count}: {phase}')

        parts = []
        budget = params | {'max_tasks': params['max_tasks'] - completed - (count - index)}
        instruction = (question + '\n\nThis call contains ONE email only. Describe its actual topic in '
                       '2–4 concise sentences; include decisions, requests, dates, or changes only if present. '
                       'Do not infer that a job suggestion means an application was submitted. '
                       'Do not add source labels or citations; the application supplies them.')
        run([message | {'source': index}], instruction, budget, render, generate, report, parts.append,
            system=SUMMARY_SYSTEM)
        completed += local_done
        heading = f'### [Source {index}](ghostmail:{quote(message["id"], safe="")}) · {markdown_text(message["subject"])}'
        sender = markdown_text(message['sender'])
        stream(f'\n\n{heading}\n\n{sender}\n\n{without_citations("".join(parts), {mail["id"] for mail in messages})}\n')
