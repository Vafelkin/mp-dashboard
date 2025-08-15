import time
import threading
from typing import Callable, TypeVar, Optional


T = TypeVar("T")


_CACHE_LOCK = threading.Lock()
_CACHE_STORE: dict[str, tuple[float, object]] = {}


def get_or_set(key: str, ttl_seconds: Optional[int], producer: Callable[[], T], force: bool = False) -> T:
    """Gets value from in-process TTL cache or computes/stores a new one.

    - key: unique cache key
    - ttl_seconds: if None or <=0, bypass cache
    - producer: function to compute value on miss
    - force: if True, bypass cache and recompute
    """
    now = time.time()
    if not force and ttl_seconds and ttl_seconds > 0:
        with _CACHE_LOCK:
            hit = _CACHE_STORE.get(key)
            if hit is not None:
                expires_at, value = hit
                if expires_at > now:
                    return value  # type: ignore[return-value]

    # Miss or force → compute
    value = producer()
    if ttl_seconds and ttl_seconds > 0:
        with _CACHE_LOCK:
            _CACHE_STORE[key] = (now + ttl_seconds, value)  # type: ignore[assignment]
    return value


def invalidate(key: str) -> None:
    with _CACHE_LOCK:
        _CACHE_STORE.pop(key, None)


def get_cached(key: str, allow_stale: bool = False):
    """Возвращает значение из кэша, без вызова producer.

    - allow_stale=True вернёт даже протухшее значение (для показа последнего состояния на дашборде).
    - Если значения нет, вернёт None.
    """
    import time
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE_STORE.get(key)
        if hit is None:
            return None
        expires_at, value = hit
        if expires_at > now or allow_stale:
            return value
        return None


