"""Schedule-order lookups for appliance lifecycle states; no physical values cached."""
import heapq


class CycleIndex:
    def __init__(self, schedule, states):
        self.schedule = schedule
        self.size = len(schedule)
        self.states = states
        self.positions = {cycle['cycle_id']: i for i, cycle in enumerate(schedule)}
        self.heaps = {state: [] for state in ('pending', 'running', 'missed')}
        self.running_positions = set()
        latest = [int(cycle['latest_start_time_step']) for cycle in schedule]
        self.ordered_latest = all(a <= b for a, b in zip(latest, latest[1:]))
        for i, cycle in enumerate(schedule):
            state = states.get(cycle['cycle_id'])
            if state in self.heaps:
                self.heaps[state].append(i)
            if state == 'running':
                self.running_positions.add(i)

    def changed(self, cycle_id, state):
        position = self.positions.get(cycle_id)
        if position is None:
            return
        self.running_positions.discard(position)
        if state == 'running':
            self.running_positions.add(position)
        if state in self.heaps:
            heapq.heappush(self.heaps[state], position)

    def first(self, state):
        heap = self.heaps[state]
        while heap:
            cycle = self.schedule[heap[0]]
            if self.states.get(cycle['cycle_id']) == state:
                return cycle
            heapq.heappop(heap)
        return None

    def running(self):
        # Snapshot permits completion/cancellation to update the index during iteration.
        return tuple(self.schedule[i] for i in sorted(self.running_positions))
