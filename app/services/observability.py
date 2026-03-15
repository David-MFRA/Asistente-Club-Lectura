import threading
from collections import deque


class ObservabilityTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._requests = {"count": 0, "errors": 0, "duration_ms_total": 0}
        self._handlers = {}
        self._jobs = {}
        self._recent_errors = deque(maxlen=25)

    def _bucket(self, container, name):
        return container.setdefault(name, {"count": 0, "errors": 0, "duration_ms_total": 0})

    def _record(self, container, name, *, duration_ms, ok, context=None):
        with self._lock:
            bucket = self._bucket(container, name)
            bucket["count"] += 1
            bucket["duration_ms_total"] += max(0, int(duration_ms or 0))
            if not ok:
                bucket["errors"] += 1
                self._recent_errors.appendleft({"name": name, **(context or {})})

    def record_request(self, method, path, status_code, duration_ms):
        with self._lock:
            self._requests["count"] += 1
            self._requests["duration_ms_total"] += max(0, int(duration_ms or 0))
            if int(status_code) >= 500:
                self._requests["errors"] += 1
                self._recent_errors.appendleft(
                    {"name": f"{method} {path}", "kind": "request", "status_code": int(status_code)}
                )

    def record_handler(self, name, *, duration_ms, ok, actor=None):
        self._record(
            self._handlers,
            name,
            duration_ms=duration_ms,
            ok=ok,
            context={"kind": "handler", "actor": actor},
        )

    def record_job(self, name, *, duration_ms, ok):
        self._record(
            self._jobs,
            name,
            duration_ms=duration_ms,
            ok=ok,
            context={"kind": "job"},
        )

    def snapshot(self):
        with self._lock:
            requests = dict(self._requests)
            handlers = {name: dict(values) for name, values in self._handlers.items()}
            jobs = {name: dict(values) for name, values in self._jobs.items()}
            recent_errors = list(self._recent_errors)

        for bucket in [requests, *handlers.values(), *jobs.values()]:
            count = bucket.get("count", 0)
            bucket["avg_duration_ms"] = int(bucket["duration_ms_total"] / count) if count else 0

        return {
            "requests": requests,
            "handlers": handlers,
            "jobs": jobs,
            "recent_errors": recent_errors,
        }
