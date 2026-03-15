import threading
import time


class SlidingWindowRateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._hits = {}

    def allow(self, key, *, limit, window_seconds):
        now = time.monotonic()
        with self._lock:
            hits = [ts for ts in self._hits.get(key, []) if now - ts < window_seconds]
            allowed = len(hits) < limit
            retry_after = 0
            if allowed:
                hits.append(now)
            elif hits:
                retry_after = max(1, int(window_seconds - (now - hits[0])))
            self._hits[key] = hits
        return allowed, retry_after


class TTLCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._entries = {}

    def get(self, key):
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return None
            expires_at, value = entry
            if expires_at <= now:
                self._entries.pop(key, None)
                return None
            return value

    def set(self, key, value, *, ttl_seconds):
        expires_at = time.monotonic() + max(1, int(ttl_seconds))
        with self._lock:
            self._entries[key] = (expires_at, value)

    def get_or_set(self, key, factory, *, ttl_seconds):
        cached = self.get(key)
        if cached is not None:
            return cached, True
        value = factory()
        self.set(key, value, ttl_seconds=ttl_seconds)
        return value, False
