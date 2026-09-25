"""In-process pub/sub used to stream download and run progress over SSE."""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, Optional, Set


class EventBus:
    def __init__(self) -> None:
        self._subscribers: Set[asyncio.Queue] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, event: Dict[str, Any]) -> None:
        """Thread-safe publish from worker threads or the event loop."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            loop.call_soon_threadsafe(self._put, q, event)

    @staticmethod
    def _put(q: asyncio.Queue, event: Dict[str, Any]) -> None:
        if q.full():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)


bus = EventBus()
