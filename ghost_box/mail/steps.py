"""Small deterministic work checklist. Describes operations, never model reasoning."""


class Steps:
    def __init__(self, publish=None):
        self.publish = publish
        self.rows = {}

    def add(self, action, sources=(), before=None):
        identifier = len(self.rows) + 1
        self.rows[identifier] = dict(step_id=identifier, action=action, sources=sorted(set(sources)),
                                     state='pending', before=before)
        self.send(identifier)
        return identifier

    def send(self, identifier):
        if self.publish:
            self.publish('step', **self.rows[identifier])

    def set(self, identifier, state, reason=None):
        self.rows[identifier]['state'] = state
        self.rows[identifier]['reason'] = reason
        self.send(identifier)

    def finish(self, status):
        for identifier, row in self.rows.items():
            if row['state'] == 'running':
                self.set(identifier, 'cancelled' if status == 'stopped' else 'failed',
                         'stopped' if status == 'stopped' else 'task_failed')
            elif row['state'] == 'pending':
                self.set(identifier, 'skipped', 'not_run')
