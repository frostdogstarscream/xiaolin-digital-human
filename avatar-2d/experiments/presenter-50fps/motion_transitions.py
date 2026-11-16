"""Schedule precomputed transitions while preserving complete action clips."""


class MotionTransitions:
    def __init__(self, plan, scheduler, lengths):
        self.plan = plan
        self.scheduler = scheduler
        self.lengths = lengths
        self.pending = None
        self.action = None
        self.phase = 'idle'
        self.action_index = 0
        self.anchor = None
        self.bridge_index = 0
        self.bridge_end = 0
        self.return_index = None
        self.completed = {name: 0 for name in plan['entries']}

    def request(self, action):
        if action not in self.plan['entries'] or action in (self.action, self.pending):
            return False
        self.pending = action
        return True

    def cancel_pending(self):
        self.pending = None
        if self.phase == 'waiting':
            self.action = None
            self.phase = 'idle'

    def _bridge(self, phase, record):
        self.phase = phase
        self.bridge_index = record['start']
        self.bridge_end = record['end']

    def _emit_bridge(self):
        token = ('transitions', self.bridge_index)
        self.bridge_index += 1
        if self.bridge_index == self.bridge_end:
            if self.phase == 'enter':
                self.phase = 'action'
                self.action_index = 0
            elif self.phase == 'return':
                self.scheduler.seek(self.return_index)
                self.completed[self.action] += 1
                self.action = None
                self.phase = 'idle'
            else:
                self.phase = 'idle'
        return token

    def next(self, previous):
        if self.phase in ('enter', 'return', 'idle_join'):
            return self._emit_bridge()
        if self.phase == 'action':
            token = (self.action, self.action_index)
            self.action_index += 1
            if self.action_index == self.lengths[self.action]:
                record = self.plan['returns'][self.action]
                self.return_index = record['idle_index']
                self._bridge('return', record)
            return token
        if self.scheduler.index is None:
            self.scheduler.select(previous)
            key = str(previous[1]) + ':' + str(self.scheduler.index)
            record = self.plan['idle_joins'].get(key) if previous[0] == 'idle' else None
            if record:
                self._bridge('idle_join', record)
                return self._emit_bridge()
        if self.phase == 'idle' and self.pending:
            next_index = self.scheduler.index
            end = self.scheduler.segments[self.scheduler.current]['end']
            eligible = [entry for entry in self.plan['entries'][self.pending]
                        if next_index <= entry['idle_index'] <= min(next_index + 29, end - 1)]
            # Anchors every 25 frames and at every segment end guarantee coverage.
            record = min(eligible, key=lambda entry: entry['cost'])
            self.action = self.pending
            self.pending = None
            self.anchor = record
            self.phase = 'waiting'
        index = self.scheduler.next(previous)
        if self.phase == 'waiting' and index == self.anchor['idle_index']:
            self._bridge('enter', self.anchor)
        return ('idle', index)


def advance(presenter, packets):
    transitions = presenter.transitions
    for packet in packets:
        info = packet.userdata
        if info.get('status') == 'start' and transitions.request(info.get('action')):
            info['motion_start'] = info['action']
    if presenter.motion_requested:
        transitions.request(presenter.motion_requested)
        presenter.motion_requested = None
    token = transitions.next(presenter.pose)
    presenter.pose = token
    presenter.motion = transitions.action
    presenter.motion_index = transitions.action_index
    if transitions.action:
        presenter.stats['last_motion'] = transitions.action
    if token[0] == 'idle':
        presenter.stats['idle_frames'] += 1
    elif token[0] == 'transitions':
        presenter.stats['transition_frames'] += 1
    else:
        presenter.stats['motion_frames'] += 1
    presenter.stats['idle_loops'] = presenter.idle_scheduler.completed
    presenter.stats['idle_segment_switches'] = len(presenter.idle_scheduler.history)
    presenter.stats['motion_phase'] = transitions.phase
    presenter.stats['actions_completed'] = transitions.completed.copy()
    return token
