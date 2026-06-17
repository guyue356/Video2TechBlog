import asyncio
from collections import defaultdict

class SSEManager:
    def __init__(self):
        self._queues = {}
        self._events = defaultdict(list)

    def get_queue(self, task_id):
        if task_id not in self._queues:
            self._queues[task_id] = asyncio.Queue()
        return self._queues[task_id]

    async def emit(self, task_id, event, data):
        payload = {"event": event, "data": data}
        self._events[task_id].append(payload)
        if task_id in self._queues:
            await self._queues[task_id].put(payload)

    def get_events(self, task_id):
        return self._events.get(task_id, [])

    def remove(self, task_id):
        self._queues.pop(task_id, None)
        self._events.pop(task_id, None)

sse_manager = SSEManager()
